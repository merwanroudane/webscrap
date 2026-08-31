"""Firecrawl adapter (audit section F).

Written against the current v2 SDK (``from firecrawl import Firecrawl``) with a
fallback to the older ``FirecrawlApp``/``scrape_url`` generation, so an existing
install keeps working.

Capabilities wired, all optional and all metered:

* **scrape** — one page as HTML/markdown, then the deterministic extractors;
* **crawl**  — a bounded set of pages from one entry point;
* **map**    — discover the URLs of a site without fetching them all;
* **search** — find candidate sources (also surfaced in Find sources).

``extract`` is deliberately not wired: the current published SDK documents it as
unavailable. It is recorded as a known gap rather than guessed at.
"""

from __future__ import annotations

import os
import time
from typing import Any

from ..config import SETTINGS
from ..exceptions import ErrorCode, ScraperError
from ..logging_config import RunLogger
from ..models import CandidateDataset, ExtractionRequest, ExtractionResult, ExtractionSchema
from ..security.url_guard import guard_url
from .base import Availability, BaseEngine


def _as_dict(value: Any) -> dict[str, Any]:
    """SDK v2 returns typed objects; v1 returned dicts."""
    if isinstance(value, dict):
        return value
    for attr in ("model_dump", "dict"):
        method = getattr(value, attr, None)
        if callable(method):
            try:
                return method()
            except Exception:
                continue
    return {
        key: getattr(value, key)
        for key in ("html", "markdown", "rawHtml", "metadata", "links", "data")
        if hasattr(value, key)
    }


class FirecrawlEngine(BaseEngine):
    name = "firecrawl"
    label = "Firecrawl (cloud)"
    capabilities = {"javascript", "static_html", "crawl", "semantic_extraction", "hosted"}
    tier = 4
    cost_mode = "metered"
    deterministic = False
    reliability = 0.78
    speed = 0.6
    requires_package = "firecrawl"
    requires_credentials = "firecrawl"

    def availability(self) -> Availability:
        try:
            import firecrawl  # noqa: F401
        except Exception:
            return Availability(
                False, "Optional package not installed.", "pip install firecrawl-py"
            )
        if not os.getenv("FIRECRAWL_API_KEY", "").strip():
            return Availability(
                False, "API key not configured.", "Set FIRECRAWL_API_KEY in your .env file."
            )
        return Availability(True)

    # ------------------------------------------------------------------ client
    def _client(self) -> tuple[Any, str]:  # pragma: no cover - optional dependency
        """Return ``(client, generation)`` for the installed SDK."""
        key = os.environ["FIRECRAWL_API_KEY"]
        try:
            from firecrawl import Firecrawl  # type: ignore

            return Firecrawl(api_key=key), "v2"
        except Exception:
            from firecrawl import FirecrawlApp  # type: ignore

            return FirecrawlApp(api_key=key), "v1"

    def scrape(self, url: str) -> tuple[str, str]:  # pragma: no cover - requires credentials
        """Return ``(html, markdown)`` for one page."""
        client, generation = self._client()
        if generation == "v2":
            document = client.scrape(url, formats=["markdown", "html"])
        else:
            try:
                document = client.scrape_url(url, formats=["markdown", "html"])
            except TypeError:
                document = client.scrape_url(url, params={"formats": ["markdown", "html"]})
        payload = _as_dict(document)
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            data = _as_dict(data)
        return str(data.get("html") or ""), str(data.get("markdown") or "")

    def map_site(
        self, url: str, limit: int = 200
    ) -> list[str]:  # pragma: no cover - requires credentials
        """Discover site URLs without fetching every page."""
        client, generation = self._client()
        if generation != "v2":
            raise ScraperError(
                ErrorCode.OPTIONAL_ENGINE_NOT_INSTALLED,
                "Site mapping needs the current firecrawl-py release.",
                {"install_hint": "pip install -U firecrawl-py"},
            )
        payload = _as_dict(client.map(url))
        links = payload.get("links") or payload.get("data") or []
        urls: list[str] = []
        for item in links[:limit]:
            if isinstance(item, str):
                urls.append(item)
            elif isinstance(item, dict) and item.get("url"):
                urls.append(str(item["url"]))
        return urls

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:  # pragma: no cover
        """Find candidate sources for the Find sources workflow."""
        client, generation = self._client()
        if generation != "v2":
            return []
        payload = _as_dict(client.search(query, limit=limit))
        results = payload.get("web") or payload.get("data") or payload.get("results") or []
        return [item for item in results if isinstance(item, dict)]

    def crawl(self, url: str, limit: int) -> list[tuple[str, str]]:  # pragma: no cover
        """Return ``(url, html)`` for a bounded crawl."""
        client, generation = self._client()
        if generation != "v2":
            raise ScraperError(
                ErrorCode.OPTIONAL_ENGINE_NOT_INSTALLED,
                "Crawling needs the current firecrawl-py release.",
                {"install_hint": "pip install -U firecrawl-py"},
            )
        payload = _as_dict(client.crawl(url, limit=limit))
        documents = payload.get("data") or []
        pages: list[tuple[str, str]] = []
        for document in documents:
            item = _as_dict(document)
            metadata = item.get("metadata") or {}
            source = str(metadata.get("sourceURL") or metadata.get("url") or url)
            html = str(item.get("html") or "")
            if html:
                pages.append((source, html))
        return pages

    # ----------------------------------------------------------------- extract
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
        if not request.allow_cloud:
            raise ScraperError(
                ErrorCode.NO_ROUTE,
                "Cloud providers are switched off for this run, so page content is not sent anywhere.",
            )
        status = self.availability()
        if not status.ready:
            code = (
                ErrorCode.API_KEY_MISSING
                if "key" in status.reason.lower()
                else ErrorCode.OPTIONAL_ENGINE_NOT_INSTALLED
            )
            raise ScraperError(code, status.reason, {"install_hint": status.install_hint})

        guarded = guard_url(request.url)
        pages_wanted = min(limit_pages or request.max_pages or 1, SETTINGS.limits.hard_max_pages)

        mode = "scrape"
        pages: list[tuple[str, str]] = []
        markdown = ""
        if pages_wanted > 1 and request.crawl.enabled:
            mode = "crawl"
            pages = self.crawl(guarded.url, pages_wanted)
        else:
            html, markdown = self.scrape(guarded.url)
            pages = [(guarded.url, html)] if html else []

        from .crawler_engines import rows_from_html

        payload_config = (candidate.payload if candidate else {}) or {}
        selector = request.selector or payload_config.get("selector")
        table_index = payload_config.get("table_index")

        records: list[dict[str, Any]] = []
        source_urls: list[str] = []
        for number, (url, html) in enumerate(pages, start=1):
            rows = rows_from_html(html, url, selector, table_index)
            if not rows:
                continue
            if request.add_provenance_columns:
                for row in rows:
                    row.setdefault("_source_url", url)
                    row.setdefault("_source_page", number)
            records.extend(rows)
            source_urls.append(url)

        if not records and markdown:
            records = [{"url": guarded.url, "markdown": markdown[:200_000]}]
            source_urls = [guarded.url]
            mode = f"{mode}+markdown"

        if not records:
            raise ScraperError(ErrorCode.NO_DATA_DETECTED, "Firecrawl returned no usable content.")

        max_rows = request.max_rows or SETTINGS.limits.max_rows
        truncated = len(records) > max_rows
        records = records[:max_rows]

        if logger:
            logger.log(
                "firecrawl",
                "extract_complete",
                url=guarded.url,
                engine=self.name,
                mode=mode,
                rows=len(records),
            )

        return self._result(
            success=True,
            records=records,
            columns=list(dict.fromkeys(key for record in records for key in record)),
            source_urls=source_urls or [guarded.url],
            started=started,
            pages_requested=max(len(pages), 1),
            pages_successful=len(source_urls),
            truncated=truncated,
            metadata={
                "provider": "firecrawl",
                "metered": True,
                "mode": mode,
                "privacy": "Firecrawl fetched the page; its content passed through their service.",
            },
        )
