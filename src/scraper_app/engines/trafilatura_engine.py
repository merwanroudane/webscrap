"""Article / main-text engine (spec section 4H).

Uses Trafilatura when installed (title, author, date, body, metadata) and
falls back to a bounded lxml text extraction so the engine is always usable.
Optionally walks a bounded list of article URLs so a section of a site becomes
one row per article.
"""

from __future__ import annotations

import re
import time
from typing import Any

from lxml import html as lxml_html

from ..config import SETTINGS
from ..exceptions import ErrorCode, ScraperError
from ..logging_config import RunLogger
from ..models import CandidateDataset, ExtractionRequest, ExtractionResult, ExtractionSchema
from .base import BaseEngine
from .http_client import fetch

_WS = re.compile(r"\s+")


def _fallback_article(html: str, url: str) -> dict[str, Any]:
    try:
        tree = lxml_html.fromstring(html)
    except Exception as exc:
        raise ScraperError(ErrorCode.CONTENT_UNSUPPORTED, "The page could not be parsed.") from exc
    for bad in tree.xpath("//script|//style|//noscript|//nav|//footer|//header|//aside"):
        parent = bad.getparent()
        if parent is not None:
            parent.remove(bad)

    title_nodes = tree.xpath("//h1") or tree.xpath("//title")
    body_nodes = tree.xpath("//article") or tree.xpath("//main") or [tree]
    text = _WS.sub(" ", body_nodes[0].text_content() or "").strip()

    meta = {
        (m.get("name") or m.get("property") or "").lower(): (m.get("content") or "")
        for m in tree.xpath("//meta[@content]")
    }
    return {
        "url": url,
        "title": _WS.sub(" ", title_nodes[0].text_content()).strip()[:300] if title_nodes else None,
        "author": meta.get("author") or meta.get("article:author") or None,
        "date": meta.get("article:published_time") or meta.get("date") or None,
        "description": meta.get("description") or meta.get("og:description") or None,
        "sitename": meta.get("og:site_name") or None,
        "text": text[:200_000],
        "text_chars": len(text),
    }


def extract_article(html: str, url: str) -> dict[str, Any]:
    """Extract one article record, preferring Trafilatura when available."""
    try:
        import json as _json

        import trafilatura  # type: ignore

        payload = trafilatura.extract(
            html,
            url=url,
            output_format="json",
            include_comments=False,
            with_metadata=True,
            favor_precision=True,
        )
        if payload:
            data = _json.loads(payload)
            text = data.get("text") or ""
            return {
                "url": url,
                "title": data.get("title"),
                "author": data.get("author"),
                "date": data.get("date"),
                "description": data.get("description"),
                "sitename": data.get("sitename"),
                "categories": data.get("categories"),
                "tags": data.get("tags"),
                "text": text[:200_000],
                "text_chars": len(text),
            }
    except Exception:
        pass
    return _fallback_article(html, url)


class ArticleEngine(BaseEngine):
    name = "article"
    label = "Article / main text"
    capabilities = {"static_html", "crawl", "local"}
    tier = 1
    cost_mode = "free"
    reliability = 0.85
    speed = 0.85

    def extract(
        self,
        request: ExtractionRequest,
        candidate: CandidateDataset | None = None,
        schema: ExtractionSchema | None = None,
        *,
        logger: RunLogger | None = None,
        progress=None,
        limit_pages: int | None = None,
    ) -> ExtractionResult:
        started = time.monotonic()
        payload = (candidate.payload if candidate else {}) or {}
        urls: list[str] = list(payload.get("urls") or [request.url])
        max_pages = min(limit_pages or request.max_pages or 1, len(urls), SETTINGS.limits.hard_max_pages)
        urls = urls[:max_pages]

        records: list[dict[str, Any]] = []
        warnings: list[str] = []
        pages_requested = 0
        pages_successful = 0

        for index, url in enumerate(urls):
            pages_requested += 1
            if progress:
                progress(index + 1, len(urls), url)
            try:
                response = fetch(url, headers=request.options.headers or None)
            except ScraperError as exc:
                if pages_successful == 0 and index == len(urls) - 1:
                    raise
                warnings.append(f"Skipped {url}: {exc.message()}")
                continue

            record = extract_article(response.text, response.url)
            if not record.get("text"):
                warnings.append(f"No readable text found at {response.url}.")
                continue
            if request.add_provenance_columns:
                record.setdefault("_source_url", response.url)
                record.setdefault("_source_page", index + 1)
            records.append(record)
            pages_successful += 1
            if logger:
                logger.log("article", "article_extracted", url=response.url, engine=self.name)

        if not records:
            raise ScraperError(ErrorCode.NO_DATA_DETECTED, "No article text could be extracted.")

        return self._result(
            success=True,
            records=records,
            columns=list(dict.fromkeys(key for record in records for key in record)),
            source_urls=[record.get("url", "") for record in records],
            started=started,
            pages_requested=pages_requested,
            pages_successful=pages_successful,
            warnings=warnings,
            metadata={"trafilatura": _trafilatura_installed()},
        )


def _trafilatura_installed() -> bool:
    try:
        import trafilatura  # noqa: F401

        return True
    except Exception:
        return False
