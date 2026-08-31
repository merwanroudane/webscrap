"""Source profiler (spec section 20).

Runs the deterministic Tier-0/Tier-1 analysis of a URL and returns a
:class:`SourceProfile` containing candidate datasets ready to show in the UI.
An optional Playwright probe (Tier-3) is used only when the static evidence
suggests JavaScript is required, or when the user explicitly asks for it.
"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urljoin, urlsplit

from lxml import html as lxml_html

from ..config import SETTINGS
from ..exceptions import ErrorCode, ScraperError
from ..logging_config import RunLogger
from ..models import (
    ApiCandidate,
    CandidateDataset,
    Confidence,
    DatasetKind,
    FieldSpec,
    NameSource,
    RobotsStatus,
    SourceProfile,
)
from ..security import content_safety
from ..security import robots as robots_module
from ..security.url_guard import guard_url, is_allowed
from . import (
    api_detector,
    file_detector,
    pagination_detector,
    repeated_patterns,
    sitemap,
    table_detector,
)
from . import structured_data as sd

_WS = re.compile(r"\s+")
_JS_FRAMEWORK_HINT = re.compile(
    r"(?i)(__NEXT_DATA__|window\.__NUXT__|ng-version|data-reactroot|react-root|vue-app|"
    r"__vite|hydrate|angular\.min\.js|require\(\[)"
)


def _text_of(html: str) -> str:
    try:
        tree = lxml_html.fromstring(html)
        for bad in tree.xpath("//script|//style|//noscript"):
            bad.getparent().remove(bad)
        return _WS.sub(" ", tree.text_content()).strip()
    except Exception:
        return _WS.sub(" ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def _links(html: str, base_url: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    try:
        tree = lxml_html.fromstring(html)
    except Exception:
        return out
    for anchor in tree.xpath("//a[@href]"):
        href = (anchor.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(base_url, href)
        if absolute.startswith(("http://", "https://")):
            out.append((absolute, _WS.sub(" ", anchor.text_content() or "").strip()))
        if len(out) >= SETTINGS.limits.max_internal_links * 2:
            break
    return out


def _title(html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", html or "", flags=re.IGNORECASE | re.DOTALL)
    return _WS.sub(" ", match.group(1)).strip()[:200] if match else None


def _strip_www(netloc: str) -> str:
    return netloc[4:] if netloc.startswith("www.") else netloc


def registrable_domain(url: str) -> str:
    """Return the registrable domain, using tldextract when it is installed.

    Without it, subdomain differences look like different sites; with it,
    news.example.co.uk and www.example.co.uk are correctly the same source.
    """
    try:
        import tldextract

        parts = tldextract.extract(url)
        if parts.domain and parts.suffix:
            return f"{parts.domain}.{parts.suffix}".lower()
    except Exception:
        pass
    return _strip_www(urlsplit(url).netloc.lower())


def _same_host(a: str, b: str) -> bool:
    return registrable_domain(a) == registrable_domain(b)


def profile_source(
    url: str,
    *,
    respect_robots: bool = True,
    use_browser: bool | None = None,
    verify_apis: bool = True,
    logger: RunLogger | None = None,
) -> SourceProfile:
    """Analyze a URL and propose candidate datasets."""
    from ..engines.http_client import fetch

    started = time.monotonic()
    guarded = guard_url(url)
    if logger:
        logger.log("profiler", "url_guard_passed", url=guarded.url)

    robots_status: RobotsStatus = (
        robots_module.check(guarded.url) if respect_robots else RobotsStatus(state="not_checked")
    )
    if logger:
        logger.log("profiler", "robots_checked", status=robots_status.state, url=guarded.url)
    if respect_robots and robots_status.state == "restricted":
        raise ScraperError(
            ErrorCode.ROBOTS_RESTRICTED,
            f"robots.txt disallows this path for {SETTINGS.user_agent.split('/')[0]}.",
            {"robots_url": robots_status.robots_url or ""},
        )

    response = fetch(guarded.url)
    content_type = response.content_type
    body_text = response.text if len(response.content) < SETTINGS.limits.max_html_bytes else ""
    fmt = file_detector.detect_format(response.url, content_type)

    profile = SourceProfile(
        url=guarded.url,
        final_url=response.url,
        status_code=response.status_code,
        content_type=content_type,
        content_length=len(response.content),
        robots=robots_status,
    )

    if response.truncated:
        profile.warnings.append(
            "The response was larger than the configured limit and was truncated for analysis."
        )

    # ---------------------------------------------------------------- direct file
    # JSON is handled by the API branch below: it supports pagination and
    # records-path discovery, which the plain file reader does not.
    if (
        fmt
        and fmt not in {"feed", "json", "jsonl"}
        and content_type not in {"text/html", "application/xhtml+xml"}
    ):
        profile.is_file = True
        profile.file_format = fmt
        profile.title = urlsplit(response.url).path.rsplit("/", 1)[-1] or response.url
        if fmt in {"json", "jsonl"}:
            profile.is_json = True
            candidate = api_detector.candidate_from_response(
                response.url,
                response.content,
                content_type=content_type,
                status=response.status_code,
                discovered_by="direct",
            )
            if candidate:
                candidate.score = max(candidate.score, 0.9)
                candidate.confidence = Confidence.HIGH
                profile.api_candidates.append(candidate)
        profile.candidates = _candidates_for_file(profile)
        profile.recommended_engine = (
            "direct_file" if file_detector.is_tabular_format(fmt) else "document"
        )
        profile.difficulty = "low"
        profile.confidence = Confidence.HIGH
        profile.elapsed_ms = int((time.monotonic() - started) * 1000)
        if logger:
            logger.log("profiler", "direct_file_detected", url=response.url, engine="direct_file")
        return profile

    # ---------------------------------------------------------------- JSON / XML
    if "json" in (content_type or "") or fmt in {"json", "jsonl"}:
        profile.is_json = True
        candidate = api_detector.candidate_from_response(
            response.url,
            response.content,
            content_type=content_type,
            status=response.status_code,
            discovered_by="direct",
        )
        if candidate:
            candidate.score = max(candidate.score, 0.92)
            candidate.confidence = Confidence.HIGH
            profile.api_candidates.append(candidate)
            try:
                profile.pagination = pagination_detector.detect_for_api(
                    response.url, response.json()
                )
            except Exception:
                pass
        profile.candidates = _candidates_for_api(profile)
        profile.recommended_engine = "json_api"
        profile.difficulty = "low"
        profile.confidence = Confidence.HIGH
        profile.elapsed_ms = int((time.monotonic() - started) * 1000)
        return profile

    if content_type in {
        "application/xml",
        "text/xml",
        "application/rss+xml",
        "application/atom+xml",
    }:
        profile.is_xml = True
        rows = sitemap.parse_feed(response.content)
        if rows:
            profile.is_feed = True
            profile.candidates = [
                CandidateDataset(
                    id="feed_0",
                    kind=DatasetKind.FEED,
                    title="RSS/Atom feed entries",
                    description=f"{len(rows)} entries published by the site itself.",
                    engine="feed",
                    rows_estimate=len(rows),
                    columns=list(rows[0].keys()),
                    sample_rows=rows[:5],
                    score=0.9,
                    confidence=Confidence.HIGH,
                    payload={"feed_url": response.url},
                    why="The site publishes a machine-readable feed, which is more stable than scraping HTML.",
                )
            ]
            profile.recommended_engine = "feed"
            profile.elapsed_ms = int((time.monotonic() - started) * 1000)
            return profile

    # ---------------------------------------------------------------- HTML
    profile.is_html = True
    html = body_text
    profile.title = _title(html)
    text = _text_of(html)
    profile.article_chars = len(text)

    profile.challenge_detected = content_safety.detect_challenge(html)
    profile.login_wall = content_safety.detect_login_wall(html)
    injections = content_safety.detect_injection(text[:20000])
    if injections:
        profile.warnings.append(
            "The page contains text addressed at automated agents. It is treated as data only."
        )
        if logger:
            logger.warn("profiler", "injection_pattern_in_page", url=response.url)

    tables, frames = table_detector.detect_tables(html, response.url)
    profile.tables = tables
    profile.table_count = len(tables)
    profile.has_tables = bool(tables)

    json_ld = sd.extract_json_ld(html)
    metadata = sd.extract_with_extruct(html, response.url)
    profile.has_json_ld = bool(json_ld)
    profile.structured_types = sd.structured_types(metadata, json_ld)

    embedded = sd.extract_embedded_json(html)
    profile.has_embedded_json = bool(embedded)
    embedded_arrays: list[tuple[str, dict[str, Any]]] = []
    for blob in embedded:
        for array in sd.find_record_arrays(blob["data"])[:3]:
            embedded_arrays.append((blob["name"], array))
    profile.embedded_json_keys = [array["path"] for _name, array in embedded_arrays][:10]

    profile.repeated_patterns = repeated_patterns.detect_repeated_patterns(html, response.url)

    links = _links(html, response.url)
    internal = [href for href, _t in links if _same_host(href, response.url) and is_allowed(href)]
    profile.internal_links = list(dict.fromkeys(internal))[: SETTINGS.limits.max_internal_links]
    profile.internal_link_count = len(profile.internal_links)
    profile.downloadable_files = file_detector.collect_file_links(links)
    profile.feeds = sitemap.discover_feeds(html, response.url)
    profile.sitemaps = list(robots_status.sitemaps)

    profile.pagination = pagination_detector.detect(response.url, html)

    api_candidates = api_detector.candidates_from_html(html, response.url)
    for name, array in embedded_arrays[:5]:
        api_candidates.append(
            ApiCandidate(
                url=response.url,
                content_type="embedded/json",
                sample_keys=list(array["keys"])[:40],
                record_count=int(array["count"]),
                records_path=array["path"],
                originating_page=response.url,
                discovered_by=f"embedded:{name}",
                score=min(0.85, 0.55 + min(array["count"] / 60.0, 0.3)),
                confidence=Confidence.from_score(0.55 + min(array["count"] / 60.0, 0.3)),
            )
        )
    if verify_apis and api_candidates:
        remote = [c for c in api_candidates if c.discovered_by == "html"]
        others = [c for c in api_candidates if c.discovered_by != "html"]
        api_candidates = others + (api_detector.verify_candidates(remote) if remote else [])
    profile.api_candidates = sorted(api_candidates, key=lambda c: c.score, reverse=True)[:12]

    # ------------------------------------------------------- JavaScript likelihood
    js_evidence: list[str] = []
    if _JS_FRAMEWORK_HINT.search(html or ""):
        js_evidence.append("Client-side framework markers found in the HTML.")
    if len(text) < 500 and len(html) > 5000:
        js_evidence.append("The HTML contains very little readable text before rendering.")
    if not profile.has_tables and not profile.repeated_patterns and len(text) < 1500:
        js_evidence.append("No tables or repeated blocks were found in the static HTML.")
    if profile.has_embedded_json and not profile.has_tables and not profile.repeated_patterns:
        js_evidence.append("Data appears to be embedded as JSON and rendered by scripts.")
    profile.js_evidence = js_evidence
    profile.requires_js = len(js_evidence) >= 2 or (
        not profile.has_tables
        and not profile.repeated_patterns
        and not profile.api_candidates
        and len(text) < 800
    )

    # ------------------------------------------------------------- browser probe
    should_probe = use_browser if use_browser is not None else profile.requires_js
    if should_probe:
        from .network_probe import probe_with_browser

        probe = probe_with_browser(response.url, logger=logger)
        if probe.get("available"):
            for candidate in probe.get("api_candidates", []):
                profile.api_candidates.append(candidate)
            rendered_html = probe.get("html") or ""
            if rendered_html and len(rendered_html) > len(html):
                rendered_tables, rendered_frames = table_detector.detect_tables(
                    rendered_html, response.url
                )
                if len(rendered_tables) > len(tables):
                    tables, frames = rendered_tables, rendered_frames
                    profile.tables = tables
                    profile.table_count = len(tables)
                    profile.has_tables = bool(tables)
                rendered_patterns = repeated_patterns.detect_repeated_patterns(
                    rendered_html, response.url
                )
                if len(rendered_patterns) > len(profile.repeated_patterns):
                    profile.repeated_patterns = rendered_patterns
                profile.article_chars = max(profile.article_chars, len(_text_of(rendered_html)))
            profile.api_candidates = sorted(
                {c.url: c for c in profile.api_candidates}.values(),
                key=lambda c: c.score,
                reverse=True,
            )[:12]
        else:
            profile.warnings.append(probe.get("reason", "Browser mode is not available."))

    profile.candidates = _build_candidates(profile, frames)
    profile.recommended_engine = profile.candidates[0].engine if profile.candidates else None
    profile.confidence = profile.candidates[0].confidence if profile.candidates else Confidence.LOW
    profile.difficulty = _difficulty(profile)
    profile.elapsed_ms = int((time.monotonic() - started) * 1000)

    if logger:
        logger.log(
            "profiler",
            "profile_complete",
            url=response.url,
            engine=profile.recommended_engine or "none",
            elapsed_ms=profile.elapsed_ms,
            candidates=len(profile.candidates),
        )
    return profile


def _difficulty(profile: SourceProfile) -> str:
    if profile.challenge_detected or profile.login_wall:
        return "high"
    if profile.candidates and profile.candidates[0].score >= 0.8:
        return "low"
    if profile.requires_js:
        return "medium" if profile.candidates else "high"
    return "medium" if profile.candidates else "high"


def _candidates_for_file(profile: SourceProfile) -> list[CandidateDataset]:
    fmt = profile.file_format or "file"
    kind = DatasetKind.DOCUMENT if file_detector.is_document_format(fmt) else DatasetKind.FILE
    return [
        CandidateDataset(
            id="file_0",
            kind=kind,
            title=f"Direct {fmt.upper()} file",
            description=f"The address points straight at a {fmt} file published by the site.",
            engine="direct_file" if kind is DatasetKind.FILE else "document",
            score=0.95 if kind is DatasetKind.FILE else 0.6,
            confidence=Confidence.HIGH if kind is DatasetKind.FILE else Confidence.MEDIUM,
            payload={"url": profile.final_url, "format": fmt},
            why="Downloading the published file is faster and more reproducible than scraping a rendered page.",
        )
    ]


def _candidates_for_api(profile: SourceProfile) -> list[CandidateDataset]:
    candidates: list[CandidateDataset] = []
    for index, api in enumerate(profile.api_candidates[:5]):
        candidates.append(
            CandidateDataset(
                id=f"api_{index}",
                kind=DatasetKind.API,
                title=f"JSON data · {urlsplit(api.url).path or '/'}",
                description=(
                    f"{api.record_count or 'unknown number of'} records"
                    + (f" at path {api.records_path}" if api.records_path else "")
                ),
                engine="json_api",
                rows_estimate=api.record_count,
                columns=api.sample_keys[:25],
                score=api.score,
                confidence=api.confidence,
                payload={
                    "url": api.url,
                    "records_path": api.records_path,
                    "discovered_by": api.discovered_by,
                },
                why="A structured JSON response is the most stable and reproducible source available.",
            )
        )
    return candidates


def _build_candidates(profile: SourceProfile, frames: list) -> list[CandidateDataset]:
    """Assemble every candidate dataset found on an HTML page, best first."""
    candidates: list[CandidateDataset] = _candidates_for_api(profile)

    for table in profile.tables:
        frame = frames[table.index] if table.index < len(frames) else None
        sample = frame.head(5).astype(str).to_dict(orient="records") if frame is not None else []
        title = table.caption or table.preceding_heading or f"Table {table.index + 1}"
        candidates.append(
            CandidateDataset(
                id=f"table_{table.index}",
                kind=DatasetKind.TABLE,
                title=f"Table {table.index + 1} · {title}"[:120],
                description=f"{table.rows} rows × {table.columns} columns",
                engine="table",
                rows_estimate=table.rows,
                columns=table.column_names,
                sample_rows=sample,
                score=min(0.93, table.score),
                confidence=table.confidence,
                payload={"table_index": table.index},
                why="An HTML table can be read deterministically with pandas — no AI or browser needed.",
            )
        )

    for index, pattern in enumerate(profile.repeated_patterns):
        candidates.append(
            CandidateDataset(
                id=f"repeated_{index}",
                kind=DatasetKind.REPEATED,
                title=f"Repeated items · {pattern.selector}",
                description=(
                    f"{pattern.item_count} similar blocks, likely fields: "
                    + ", ".join(f.name for f in pattern.fields[:6])
                ),
                engine="repeated_dom",
                rows_estimate=pattern.item_count,
                columns=[f.name for f in pattern.fields],
                sample_rows=pattern.sample_rows,
                score=pattern.score,
                confidence=pattern.confidence,
                payload={
                    "selector": pattern.selector,
                    "fields": [f.model_dump() for f in pattern.fields],
                },
                why="The page repeats the same block structure, so each block becomes one row.",
            )
        )

    if profile.structured_types:
        candidates.append(
            CandidateDataset(
                id="structured_0",
                kind=DatasetKind.STRUCTURED,
                title="Structured metadata (schema.org)",
                description="Types: " + ", ".join(profile.structured_types[:6]),
                engine="structured",
                columns=[],
                score=0.62,
                confidence=Confidence.MEDIUM,
                payload={"types": profile.structured_types},
                why="The publisher embeds machine-readable metadata describing the page content.",
            )
        )

    if profile.article_chars >= 400:
        candidates.append(
            CandidateDataset(
                id="article_0",
                kind=DatasetKind.ARTICLE,
                title="Article / main text",
                description=f"About {profile.article_chars:,} characters of readable text with metadata.",
                engine="article",
                columns=["title", "author", "date", "text", "url"],
                score=0.55 if (profile.has_tables or profile.repeated_patterns) else 0.7,
                confidence=Confidence.MEDIUM,
                payload={},
                why="The page reads as an article, so title/author/date/body are extracted as one record.",
            )
        )

    if profile.downloadable_files:
        data_files = [f for f in profile.downloadable_files if f["kind"] == "data"]
        candidates.append(
            CandidateDataset(
                id="links_files",
                kind=DatasetKind.LINKS,
                title="Files linked from this page",
                description=f"{len(profile.downloadable_files)} downloadable files "
                f"({len(data_files)} data files)",
                engine="links",
                rows_estimate=len(profile.downloadable_files),
                columns=["url", "format", "label", "kind"],
                sample_rows=profile.downloadable_files[:5],
                score=0.75 if data_files else 0.45,
                confidence=Confidence.from_score(0.75 if data_files else 0.45),
                payload={"files": profile.downloadable_files},
                why="Published data files are usually the cleanest source; here is the list found on the page.",
            )
        )

    if profile.internal_link_count:
        candidates.append(
            CandidateDataset(
                id="links_internal",
                kind=DatasetKind.LINKS,
                title="Links on this page",
                description=f"{profile.internal_link_count} internal links",
                engine="links",
                rows_estimate=profile.internal_link_count,
                columns=["url", "text"],
                score=0.3,
                confidence=Confidence.LOW,
                payload={"internal": True},
                why="Useful as a starting point for a bounded multi-page crawl.",
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


def build_field_specs(
    columns: list[str], name_source: NameSource = NameSource.SOURCE_NATIVE
) -> list[FieldSpec]:
    return [
        FieldSpec(
            name=str(col), label=str(col), name_source=name_source, confidence=Confidence.HIGH
        )
        for col in columns
    ]
