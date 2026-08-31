"""Engines backed by the provider protocols (audit sections N and O).

* :class:`ManagedFetchEngine`    — fetch through ZenRows/ScrapingBee/… then run
  the ordinary deterministic extractors on the HTML that comes back.
* :class:`SemanticContentEngine` — Diffbot / Jina Reader for prose-heavy pages.

Both are thin: the provider does the network work, the existing detectors do
the extraction, so results have the same shape as a local run.
"""

from __future__ import annotations

import time
from typing import Any

from ..config import SETTINGS
from ..exceptions import ErrorCode, ScraperError
from ..logging_config import RunLogger
from ..models import CandidateDataset, ExtractionRequest, ExtractionResult, ExtractionSchema
from ..providers import managed_fetch, semantic_content
from ..security.url_guard import guard_url
from .base import Availability, BaseEngine
from .crawler_engines import rows_from_html


class ManagedFetchEngine(BaseEngine):
    name = "managed_fetch"
    label = "Managed fetch provider"
    capabilities = {"static_html", "javascript", "hosted"}
    tier = 4
    cost_mode = "metered"
    deterministic = True  # the provider only fetches; parsing stays deterministic
    reliability = 0.78
    speed = 0.6

    def availability(self) -> Availability:
        provider = managed_fetch.configured_provider()
        if provider is None:
            return Availability(
                False,
                "No managed fetch provider is configured.",
                "Add a key such as ZENROWS_API_KEY or SCRAPINGBEE_API_KEY to your .env file.",
            )
        return Availability(True)

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
                "Cloud providers are switched off for this run, so no managed provider is used.",
            )

        provider = managed_fetch.configured_provider(request.engine_preference)
        if provider is None:
            status = self.availability()
            raise ScraperError(
                ErrorCode.API_KEY_MISSING, status.reason, {"install_hint": status.install_hint}
            )

        payload = (candidate.payload if candidate else {}) or {}
        selector = request.selector or payload.get("selector")
        table_index = payload.get("table_index")

        plan = request.pagination
        pages_wanted = min(limit_pages or request.max_pages or 1, SETTINGS.limits.hard_max_pages)
        urls: list[str] = []
        if plan.url_template and "{page}" in plan.url_template and pages_wanted > 1:
            urls = [
                plan.url_template.replace("{page}", str(plan.start + index * max(plan.step, 1)))
                for index in range(pages_wanted)
            ]
        else:
            urls = [request.url]

        records: list[dict[str, Any]] = []
        source_urls: list[str] = []
        warnings: list[str] = []

        for number, url in enumerate(urls, start=1):
            if progress:
                progress(number, len(urls), url)
            result = provider.fetch(
                managed_fetch.FetchRequest(url=url, render_js=request.allow_browser)
            )
            rows = rows_from_html(result.html, result.url, selector, table_index)
            if not rows:
                warnings.append(f"No rows found on {url}")
                continue
            if request.add_provenance_columns:
                for row in rows:
                    row.setdefault("_source_url", result.url)
                    row.setdefault("_source_page", number)
            records.extend(rows)
            source_urls.append(result.url)

        if not records:
            raise ScraperError(
                ErrorCode.NO_DATA_DETECTED,
                f"{provider.label} returned pages with no extractable rows.",
            )

        max_rows = request.max_rows or SETTINGS.limits.max_rows
        truncated = len(records) > max_rows
        records = records[:max_rows]

        if logger:
            logger.log(
                "managed_fetch",
                "extract_complete",
                engine=self.name,
                provider=provider.id,
                rows=len(records),
            )

        return self._result(
            success=True,
            records=records,
            columns=list(dict.fromkeys(key for record in records for key in record)),
            source_urls=source_urls,
            started=started,
            pages_requested=len(urls),
            pages_successful=len(source_urls),
            truncated=truncated,
            warnings=warnings[:10],
            metadata={"provider": provider.id, "metered": True},
        )


class SemanticContentEngine(BaseEngine):
    name = "semantic_content"
    label = "Semantic content provider"
    capabilities = {"semantic_extraction", "hosted"}
    tier = 4
    cost_mode = "metered"
    deterministic = False
    reliability = 0.75
    speed = 0.65

    def availability(self) -> Availability:
        provider = semantic_content.configured_provider()
        if provider is None:
            return Availability(
                False,
                "No semantic content provider is configured.",
                "Add DIFFBOT_TOKEN or JINA_API_KEY to your .env file.",
            )
        return Availability(True)

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
                "Cloud providers are switched off for this run, so no content provider is used.",
            )

        provider = semantic_content.configured_provider(request.engine_preference)
        if provider is None:
            status = self.availability()
            raise ScraperError(
                ErrorCode.API_KEY_MISSING, status.reason, {"install_hint": status.install_hint}
            )

        payload = (candidate.payload if candidate else {}) or {}
        urls = [str(u) for u in payload.get("urls", [])] or [request.url]
        urls = urls[: (limit_pages or request.max_pages or 1)]

        records: list[dict[str, Any]] = []
        for number, url in enumerate(urls, start=1):
            if progress:
                progress(number, len(urls), url)
            guard_url(url)
            document = provider.read(url)
            record = document.as_record()
            if request.add_provenance_columns:
                record.setdefault("_source_url", document.url)
                record.setdefault("_source_page", number)
            records.append(record)

        if not records:
            raise ScraperError(ErrorCode.NO_DATA_DETECTED, f"{provider.label} returned no content.")

        if logger:
            logger.log(
                "semantic_content",
                "extract_complete",
                engine=self.name,
                provider=provider.id,
                rows=len(records),
            )

        return self._result(
            success=True,
            records=records,
            columns=list(dict.fromkeys(key for record in records for key in record)),
            source_urls=[str(r.get("url", "")) for r in records],
            started=started,
            pages_requested=len(urls),
            pages_successful=len(records),
            metadata={"provider": provider.id, "metered": True},
        )
