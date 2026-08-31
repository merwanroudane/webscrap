"""Crawl4AI adapter (optional, Tier 3/4).

Local-first modern engine. Used when installed and when the deterministic
engines could not produce a dataset. The adapter runs Crawl4AI in *markdown /
DOM* mode by default — no LLM call — and only uses its LLM extraction strategy
when the user has explicitly allowed AI and a provider key exists.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from ..exceptions import ErrorCode, ScraperError
from ..logging_config import RunLogger
from ..models import CandidateDataset, ExtractionRequest, ExtractionResult, ExtractionSchema
from ..security.url_guard import guard_url
from .base import Availability, BaseEngine


class Crawl4aiEngine(BaseEngine):
    name = "crawl4ai"
    label = "Crawl4AI (local)"
    capabilities = {"javascript", "static_html", "semantic_extraction", "local"}
    tier = 4
    cost_mode = "local_compute"
    deterministic = False
    reliability = 0.7
    speed = 0.45
    requires_package = "crawl4ai"

    def availability(self) -> Availability:
        try:
            import crawl4ai  # noqa: F401
        except Exception:
            return Availability(
                False,
                "Optional package not installed.",
                "pip install crawl4ai && crawl4ai-setup",
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
        status = self.availability()
        if not status.ready:
            raise ScraperError(
                ErrorCode.OPTIONAL_ENGINE_NOT_INSTALLED,
                status.reason,
                {"install_hint": status.install_hint},
            )

        guarded = guard_url(request.url)
        result = asyncio.run(self._run(guarded.url))
        html = result.get("html") or ""
        if not html:
            raise ScraperError(ErrorCode.NO_DATA_DETECTED, "Crawl4AI returned no content.")

        # Deterministic extraction from the rendered DOM — no LLM involved.
        from ..discovery import repeated_patterns, table_detector

        records: list[dict[str, Any]] = []
        columns: list[str] = []
        _cands, frames = table_detector.detect_tables(html, guarded.url)
        if frames:
            frame = frames[0]
            records = frame.to_dict(orient="records")
            columns = [str(c) for c in frame.columns]
        else:
            patterns = repeated_patterns.detect_repeated_patterns(html, guarded.url)
            if patterns:
                records = repeated_patterns.extract_rows_with_selector(
                    html, patterns[0].selector, patterns[0].fields, guarded.url
                )
        if not records and result.get("markdown"):
            records = [{"url": guarded.url, "markdown": result["markdown"][:200_000]}]
            columns = ["url", "markdown"]

        if not records:
            raise ScraperError(ErrorCode.NO_DATA_DETECTED, "Crawl4AI produced no structured rows.")

        if request.add_provenance_columns:
            for record in records:
                record.setdefault("_source_url", guarded.url)

        if logger:
            logger.log("crawl4ai", "extract_complete", url=guarded.url, engine=self.name, rows=len(records))

        return self._result(
            success=True,
            records=records,
            columns=columns or list(records[0].keys()),
            source_urls=[guarded.url],
            started=started,
            pages_requested=1,
            pages_successful=1,
            metadata={"mode": "dom", "llm_used": False},
        )

    async def _run(self, url: str) -> dict[str, Any]:  # pragma: no cover - optional dependency
        from crawl4ai import AsyncWebCrawler  # type: ignore

        async with AsyncWebCrawler(verbose=False) as crawler:
            result = await crawler.arun(url=url)
        html = getattr(result, "cleaned_html", None) or getattr(result, "html", "") or ""
        markdown = getattr(result, "markdown", "") or ""
        if not isinstance(markdown, str):
            markdown = str(getattr(markdown, "raw_markdown", "") or "")
        return {"html": html, "markdown": markdown}
