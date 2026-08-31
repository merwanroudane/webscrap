"""API / JSON endpoint detection from page evidence (spec section 21).

No brute-forcing of common endpoint names: candidates come only from evidence
present in the page (links, scripts, config objects, feeds) or from the
Playwright network probe. Authorization headers and cookies are never stored.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qsl, urljoin, urlsplit

from ..config import SETTINGS
from ..models import ApiCandidate, Confidence
from ..security.url_guard import is_allowed
from .structured_data import find_record_arrays

_URL_IN_SCRIPT = re.compile(
    r"""["'](?P<url>(?:https?:)?//[^"'\s]+?/(?:api|v\d|rest|graphql|data|json)[^"'\s]*|/(?:api|rest|v\d|data)/[^"'\s]{2,120})["']"""
)
_API_PATH_HINT = re.compile(
    r"(?i)(/api/|/rest/|/v\d+/|/data/|\.json(\?|$)|format=json|output=json)"
)
_DATASET_KEY_HINT = re.compile(
    r"(?i)^(data|items|results|records|rows|values|observations|series|entries|features|content|list|docs)$"
)


def _score_candidate(url: str, keys: list[str], record_count: int | None) -> float:
    score = 0.4
    if _API_PATH_HINT.search(url):
        score += 0.2
    if record_count:
        score += min(record_count / 50.0, 1.0) * 0.2
    if keys:
        score += min(len(keys) / 8.0, 1.0) * 0.15
    if any(_DATASET_KEY_HINT.match(k) for k in keys):
        score += 0.05
    return max(0.05, min(score, 0.97))


def candidates_from_html(html: str, base_url: str) -> list[ApiCandidate]:
    """Find endpoint URLs referenced by the page itself."""
    found: dict[str, ApiCandidate] = {}

    for match in _URL_IN_SCRIPT.finditer(html or ""):
        raw = match.group("url")
        if raw.startswith("//"):
            raw = f"{urlsplit(base_url).scheme}:{raw}"
        absolute = urljoin(base_url, raw)
        if not absolute.startswith(("http://", "https://")) or not is_allowed(absolute):
            continue
        if not _API_PATH_HINT.search(absolute):
            continue
        if absolute in found:
            continue
        found[absolute] = ApiCandidate(
            url=absolute,
            originating_page=base_url,
            query_params=dict(parse_qsl(urlsplit(absolute).query))
            if urlsplit(absolute).query
            else {},
            discovered_by="html",
            score=_score_candidate(absolute, [], None),
            confidence=Confidence.LOW,
        )
        if len(found) >= 25:
            break

    return list(found.values())


def describe_json_payload(payload: Any) -> tuple[str | None, list[str], int | None]:
    """Return ``(records_path, keys, count)`` for a JSON document."""
    arrays = find_record_arrays(payload)
    if arrays:
        best = arrays[0]
        return (
            (None if best["path"] == "$" else best["path"]),
            list(best["keys"]),
            int(best["count"]),
        )
    if isinstance(payload, dict):
        return None, list(payload.keys())[:60], None
    if isinstance(payload, list):
        return None, [], len(payload)
    return None, [], None


def candidate_from_response(
    url: str,
    body: str | bytes,
    *,
    content_type: str | None = None,
    status: int | None = 200,
    originating_page: str | None = None,
    discovered_by: str = "network",
    method: str = "GET",
) -> ApiCandidate | None:
    """Build a candidate from an actual JSON response body."""
    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="replace")
    body = body[: SETTINGS.limits.max_json_sample_bytes]
    try:
        payload = json.loads(body)
    except Exception:
        return None

    records_path, keys, count = describe_json_payload(payload)
    if not keys and not count:
        return None

    score = _score_candidate(url, keys, count)
    return ApiCandidate(
        url=url,
        method=method,
        content_type=content_type or "application/json",
        status=status,
        sample_keys=keys[:40],
        record_count=count,
        records_path=records_path,
        response_size=len(body),
        originating_page=originating_page,
        query_params=dict(parse_qsl(urlsplit(url).query)) if urlsplit(url).query else {},
        discovered_by=discovered_by,
        score=score,
        confidence=Confidence.from_score(score),
    )


def verify_candidates(
    candidates: list[ApiCandidate], fetcher=None, limit: int = 4
) -> list[ApiCandidate]:
    """Call the most promising candidates once to confirm they return records."""
    if fetcher is None:
        from ..engines.http_client import fetch as fetcher  # type: ignore

    verified: list[ApiCandidate] = []
    for candidate in sorted(candidates, key=lambda c: c.score, reverse=True)[:limit]:
        if candidate.record_count:  # already verified by the network probe
            verified.append(candidate)
            continue
        try:
            response = fetcher(
                candidate.url,
                max_bytes=SETTINGS.limits.max_json_sample_bytes,
                max_retries=0,
            )
        except Exception:
            continue
        if "json" not in (response.content_type or ""):
            continue
        confirmed = candidate_from_response(
            response.url,
            response.content,
            content_type=response.content_type,
            status=response.status_code,
            originating_page=candidate.originating_page,
            discovered_by=candidate.discovered_by,
        )
        if confirmed:
            verified.append(confirmed)

    remaining = [c for c in candidates if c.url not in {v.url for v in verified}]
    return verified + remaining[: max(0, 10 - len(verified))]


def detect_cursor_field(payload: Any) -> str | None:
    """Find a cursor/next-page token key in an API response."""
    if not isinstance(payload, dict):
        return None
    for key in payload:
        if re.fullmatch(
            r"(?i)(next|next_page|next_cursor|next_page_token|nextPageToken|cursor|after|continuation.*)",
            str(key),
        ):
            value = payload[key]
            if isinstance(value, (str, int)) and str(value).strip():
                return str(key)
    for container in ("meta", "pagination", "paging", "page", "info"):
        nested = payload.get(container)
        if isinstance(nested, dict):
            found = detect_cursor_field(nested)
            if found:
                return f"{container}.{found}"
    return None
