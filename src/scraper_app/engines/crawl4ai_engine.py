"""Crawl4AI adapter (audit section E).

Two modes, tried in this order:

1. **DOM/Markdown (default, free, local)** — Crawl4AI renders the page and the
   ordinary deterministic detectors read tables or repeated blocks out of it.
2. **Semantic/LLM (opt-in)** — only when deterministic extraction produced
   nothing *and* the researcher enabled AI *and* a model key is configured.

Rule from the specification, enforced here: an LLM is never asked to parse a
table that a parser can read. The result metadata always records which mode ran
and, when a model was used, which provider saw the content.
"""

from __future__ import annotations

import time
from typing import Any

from ..ai import service as ai_service
from ..ai.base import AIMode
from ..async_runner import run_async_safely
from ..config import SETTINGS
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
    reliability = 0.72
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

    def setup_complete(self) -> bool:
        """Crawl4AI needs its browser assets fetched once via ``crawl4ai-setup``."""
        try:
            from ..discovery.network_probe import playwright_available

            return playwright_available()[0]
        except Exception:
            return False

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
        rendered = run_async_safely(lambda: self._run(guarded.url))
        html = rendered.get("html") or ""
        markdown = rendered.get("markdown") or ""
        if not html and not markdown:
            raise ScraperError(ErrorCode.NO_DATA_DETECTED, "Crawl4AI returned no content.")

        # ------------------------------------------------------- deterministic
        records, columns = self._deterministic(html, guarded.url)
        mode = "dom"
        ai_usage: dict[str, Any] = {}

        # ------------------------------------------------------------ semantic
        if not records:
            allowed = ai_service.ai_enabled(
                AIMode.ALWAYS if request.allow_ai else AIMode.DISABLED,
                deterministic_succeeded=False,
            )
            provider = ai_service.get_provider() if allowed else None
            if provider is not None:
                usage_log = ai_service.AIUsageLog()
                wanted = schema.field_names() if schema and schema.fields else None
                proposed = ai_service.extract_records(
                    instruction=request.user_goal
                    or "Extract the main tabular dataset visible in this page.",
                    page_content=markdown or html,
                    columns=wanted,
                    usage_log=usage_log,
                )
                if proposed:
                    records = proposed
                    columns = list(dict.fromkeys(k for row in records for k in row))
                    mode = "semantic"
                    ai_usage = usage_log.as_dict()
                    if logger:
                        logger.log(
                            "crawl4ai",
                            "semantic_extraction_used",
                            engine=self.name,
                            provider=provider.name,
                            rows=len(records),
                        )

        # ------------------------------------------------- markdown last resort
        if not records and markdown:
            records = [{"url": guarded.url, "markdown": markdown[:200_000]}]
            columns = ["url", "markdown"]
            mode = "markdown"

        if not records:
            raise ScraperError(ErrorCode.NO_DATA_DETECTED, "Crawl4AI produced no structured rows.")

        if request.add_provenance_columns:
            for record in records:
                record.setdefault("_source_url", guarded.url)

        max_rows = request.max_rows or SETTINGS.limits.max_rows
        truncated = len(records) > max_rows
        records = records[:max_rows]

        if logger:
            logger.log(
                "crawl4ai",
                "extract_complete",
                url=guarded.url,
                engine=self.name,
                mode=mode,
                rows=len(records),
            )

        return self._result(
            success=True,
            records=records,
            columns=columns or list(records[0].keys()),
            source_urls=[guarded.url],
            started=started,
            pages_requested=1,
            pages_successful=1,
            truncated=truncated,
            metadata={
                "mode": mode,
                "llm_used": mode == "semantic",
                "ai_usage": ai_usage,
                "privacy": (
                    "A bounded page excerpt was sent to the configured model provider."
                    if mode == "semantic"
                    else "Everything stayed on this machine."
                ),
            },
        )

    # ------------------------------------------------------------------ helpers
    def _deterministic(self, html: str, url: str) -> tuple[list[dict[str, Any]], list[str]]:
        from ..discovery import repeated_patterns, table_detector

        if not html:
            return [], []
        _candidates, frames = table_detector.detect_tables(html, url)
        if frames:
            frame = frames[0]
            return frame.to_dict(orient="records"), [str(c) for c in frame.columns]
        patterns = repeated_patterns.detect_repeated_patterns(html, url)
        if patterns:
            rows = repeated_patterns.extract_rows_with_selector(
                html, patterns[0].selector, patterns[0].fields, url
            )
            if rows:
                return rows, list(rows[0].keys())
        return [], []

    async def _run(self, url: str) -> dict[str, Any]:  # pragma: no cover - optional dependency
        from crawl4ai import AsyncWebCrawler  # type: ignore

        async with AsyncWebCrawler(verbose=False) as crawler:
            result = await crawler.arun(url=url)

        html = getattr(result, "cleaned_html", None) or getattr(result, "html", "") or ""
        markdown = getattr(result, "markdown", "") or ""
        if not isinstance(markdown, str):
            markdown = str(getattr(markdown, "raw_markdown", "") or "")
        return {"html": html, "markdown": markdown}
