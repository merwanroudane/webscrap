"""Firecrawl adapter (optional, cloud, metered).

Only ever used when the user explicitly allows cloud providers *and* a
``FIRECRAWL_API_KEY`` is configured. The preflight card always states that page
content will leave the machine before such a run starts.
"""

from __future__ import annotations

import os
import time
from typing import Any

from ..exceptions import ErrorCode, ScraperError
from ..logging_config import RunLogger
from ..models import CandidateDataset, ExtractionRequest, ExtractionResult, ExtractionSchema
from ..security.url_guard import guard_url
from .base import Availability, BaseEngine


class FirecrawlEngine(BaseEngine):
    name = "firecrawl"
    label = "Firecrawl (cloud)"
    capabilities = {"javascript", "static_html", "semantic_extraction", "hosted"}
    tier = 4
    cost_mode = "metered"
    deterministic = False
    reliability = 0.75
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
        html, markdown = self._scrape(guarded.url)

        from ..discovery import repeated_patterns, table_detector

        records: list[dict[str, Any]] = []
        columns: list[str] = []
        if html:
            _cands, frames = table_detector.detect_tables(html, guarded.url)
            if frames:
                records = frames[0].to_dict(orient="records")
                columns = [str(c) for c in frames[0].columns]
            else:
                patterns = repeated_patterns.detect_repeated_patterns(html, guarded.url)
                if patterns:
                    records = repeated_patterns.extract_rows_with_selector(
                        html, patterns[0].selector, patterns[0].fields, guarded.url
                    )
        if not records and markdown:
            records = [{"url": guarded.url, "markdown": markdown[:200_000]}]
            columns = ["url", "markdown"]
        if not records:
            raise ScraperError(ErrorCode.NO_DATA_DETECTED, "Firecrawl returned no usable content.")

        if request.add_provenance_columns:
            for record in records:
                record.setdefault("_source_url", guarded.url)

        if logger:
            logger.log("firecrawl", "extract_complete", url=guarded.url, engine=self.name, rows=len(records))

        return self._result(
            success=True,
            records=records,
            columns=columns or list(records[0].keys()),
            source_urls=[guarded.url],
            started=started,
            pages_requested=1,
            pages_successful=1,
            metadata={"provider": "firecrawl", "metered": True},
        )

    def _scrape(self, url: str) -> tuple[str, str]:  # pragma: no cover - optional dependency
        from firecrawl import FirecrawlApp  # type: ignore

        app = FirecrawlApp(api_key=os.environ["FIRECRAWL_API_KEY"])
        try:
            response = app.scrape_url(url, formats=["markdown", "html"])
        except TypeError:  # older SDK signature
            response = app.scrape_url(url, params={"formats": ["markdown", "html"]})

        if isinstance(response, dict):
            data = response.get("data", response)
            return str(data.get("html") or ""), str(data.get("markdown") or "")
        return str(getattr(response, "html", "") or ""), str(getattr(response, "markdown", "") or "")
