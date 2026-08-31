"""Agentic browser workflows (audit section L).

Stagehand, Browser Use and Skyvern drive a browser from a natural-language
task. They are the last resort in the routing order: expensive, slow and
non-deterministic, and only worth using for genuine multi-step interaction —
choosing filters, stepping through a public wizard, paging a widget that has no
URL.

Hard limits that apply to all three:

* the target URL passes the SSRF guard first;
* they run only when the researcher has enabled agentic mode *and* cloud/AI
  where the provider needs it;
* the task text is prefixed with an instruction that forbids logging in,
  solving challenges, defeating paywalls or bypassing access controls;
* whatever the agent returns is parsed by the ordinary deterministic
  extractors, so a fabricated answer cannot become a dataset.
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
from .crawler_engines import rows_from_html

#: Prepended to every agent task. Not a suggestion.
SAFETY_PREAMBLE = (
    "You are collecting publicly visible data for research. "
    "Do not log in, do not create an account, do not solve a CAPTCHA or bot check, "
    "do not bypass a paywall, and do not accept terms on the user's behalf. "
    "If any of those is required, stop and report that the page is not publicly accessible. "
)


def build_task(request: ExtractionRequest, schema: ExtractionSchema | None) -> str:
    """Compose the agent instruction from the researcher's own words."""
    wanted = schema.field_names() if schema and schema.fields else []
    goal = (request.user_goal or "").strip()
    if not goal:
        goal = (
            f"Collect the visible records with these fields: {', '.join(wanted)}."
            if wanted
            else "Collect the main tabular data visible on the page."
        )
    return SAFETY_PREAMBLE + goal


class _AgenticEngine(BaseEngine):
    """Shared guards for the agentic engines."""

    capabilities = {"javascript", "natural_language_actions", "semantic_extraction"}
    tier = 5
    deterministic = False

    def _check(self, request: ExtractionRequest) -> None:
        if not request.allow_agentic:
            raise ScraperError(
                ErrorCode.NO_ROUTE,
                "Agentic browsing is switched off for this run. Enable it in Advanced mode "
                "if this source genuinely needs multi-step interaction.",
            )
        status = self.availability()
        if not status.ready:
            code = (
                ErrorCode.API_KEY_MISSING
                if "key" in status.reason.lower()
                else ErrorCode.OPTIONAL_ENGINE_NOT_INSTALLED
            )
            raise ScraperError(code, status.reason, {"install_hint": status.install_hint})

    def _from_html(
        self,
        request: ExtractionRequest,
        candidate: CandidateDataset | None,
        html: str,
        url: str,
        started: float,
        logger: RunLogger | None,
        metadata: dict[str, Any],
    ) -> ExtractionResult:
        payload = (candidate.payload if candidate else {}) or {}
        records = rows_from_html(
            html, url, request.selector or payload.get("selector"), payload.get("table_index")
        )
        if not records:
            raise ScraperError(
                ErrorCode.NO_DATA_DETECTED,
                f"{self.label} finished but the resulting page held no extractable rows.",
            )
        if request.add_provenance_columns:
            for record in records:
                record.setdefault("_source_url", url)

        max_rows = request.max_rows or SETTINGS.limits.max_rows
        truncated = len(records) > max_rows
        records = records[:max_rows]

        if logger:
            logger.log(self.name, "agent_complete", engine=self.name, url=url, rows=len(records))

        return self._result(
            success=True,
            records=records,
            columns=list(dict.fromkeys(key for record in records for key in record)),
            source_urls=[url],
            started=started,
            pages_requested=1,
            pages_successful=1,
            truncated=truncated,
            metadata=metadata,
        )


class StagehandEngine(_AgenticEngine):
    """Browserbase Stagehand: act/extract/observe on top of Playwright."""

    name = "stagehand"
    label = "Stagehand (agentic)"
    cost_mode = "metered"
    reliability = 0.6
    speed = 0.25
    requires_package = "stagehand"

    def availability(self) -> Availability:
        try:
            import stagehand  # noqa: F401
        except Exception:
            return Availability(False, "Optional package not installed.", "pip install stagehand")
        if not (
            os.getenv("BROWSERBASE_API_KEY", "").strip() and os.getenv("MODEL_API_KEY", "").strip()
        ):
            # Stagehand needs a browser session and a model to plan actions.
            if not any(
                os.getenv(key, "").strip()
                for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MODEL_API_KEY")
            ):
                return Availability(
                    False,
                    "Stagehand needs a model key (ANTHROPIC_API_KEY or OPENAI_API_KEY).",
                    "Add a model key, and BROWSERBASE_API_KEY for hosted sessions.",
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
        self._check(request)
        guarded = guard_url(request.url)
        task = build_task(request, schema)
        html = self._run(guarded.url, task)
        return self._from_html(
            request, candidate, html, guarded.url, started, logger, {"agent": "stagehand"}
        )

    def _run(self, url: str, task: str) -> str:  # pragma: no cover - requires credentials
        from stagehand import Stagehand  # type: ignore

        env = "BROWSERBASE" if os.getenv("BROWSERBASE_API_KEY", "").strip() else "LOCAL"
        stagehand = Stagehand(env=env)
        try:
            stagehand.init()
            page = stagehand.page
            page.goto(url)
            page.act(task)
            return page.content()
        finally:
            try:
                stagehand.close()
            except Exception:
                pass


class BrowserUseEngine(_AgenticEngine):
    """Browser Use: an LLM-driven agent over a local Playwright browser."""

    name = "browser_use"
    label = "Browser Use (agentic)"
    cost_mode = "metered"
    reliability = 0.58
    speed = 0.2
    requires_package = "browser_use"

    def availability(self) -> Availability:
        try:
            import browser_use  # noqa: F401
        except Exception:
            return Availability(False, "Optional package not installed.", "pip install browser-use")
        if not any(
            os.getenv(key, "").strip()
            for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")
        ):
            return Availability(
                False,
                "Browser Use needs a model key to plan actions.",
                "Set OPENAI_API_KEY, ANTHROPIC_API_KEY or GOOGLE_API_KEY.",
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
        self._check(request)
        guarded = guard_url(request.url)
        task = f"{build_task(request, schema)} Start at {guarded.url}."
        html = self._run(task)
        return self._from_html(
            request, candidate, html, guarded.url, started, logger, {"agent": "browser_use"}
        )

    def _run(self, task: str) -> str:  # pragma: no cover - requires credentials
        import asyncio

        from browser_use import Agent  # type: ignore

        async def run() -> str:
            agent = Agent(task=task)
            history = await agent.run(max_steps=12)
            for getter in ("final_result", "extracted_content"):
                value = getattr(history, getter, None)
                if callable(value):
                    result = value()
                    if result:
                        return str(result)
            return str(history)

        return asyncio.run(run())


class SkyvernEngine(_AgenticEngine):
    """Skyvern: hosted agent for multi-step public workflows."""

    name = "skyvern"
    label = "Skyvern (agentic)"
    cost_mode = "metered"
    reliability = 0.55
    speed = 0.2
    requires_credentials = "skyvern"

    def availability(self) -> Availability:
        if not os.getenv("SKYVERN_API_KEY", "").strip():
            return Availability(
                False, "API key not configured.", "Set SKYVERN_API_KEY in your .env file."
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
        self._check(request)
        if not request.allow_cloud:
            raise ScraperError(
                ErrorCode.NO_ROUTE,
                "Skyvern is a hosted service and cloud providers are switched off.",
            )
        guarded = guard_url(request.url)
        records = self._run(guarded.url, build_task(request, schema))
        if not records:
            raise ScraperError(ErrorCode.NO_DATA_DETECTED, "Skyvern returned no structured data.")

        if request.add_provenance_columns:
            for record in records:
                record.setdefault("_source_url", guarded.url)

        if logger:
            logger.log("skyvern", "agent_complete", engine=self.name, rows=len(records))

        return self._result(
            success=True,
            records=records,
            columns=list(dict.fromkeys(key for record in records for key in record)),
            source_urls=[guarded.url],
            started=started,
            pages_requested=1,
            pages_successful=1,
            metadata={"agent": "skyvern", "metered": True},
        )

    def _run(
        self, url: str, task: str
    ) -> list[dict[str, Any]]:  # pragma: no cover - requires credentials
        import httpx

        base = os.getenv("SKYVERN_BASE_URL", "https://api.skyvern.com").rstrip("/")
        try:
            with httpx.Client(timeout=SETTINGS.limits.browser_timeout * 4) as client:
                response = client.post(
                    f"{base}/v1/run/tasks",
                    headers={
                        "x-api-key": os.environ["SKYVERN_API_KEY"],
                        "Content-Type": "application/json",
                    },
                    json={"prompt": task, "url": url, "engine": "skyvern-2.0"},
                )
        except httpx.HTTPError as exc:
            raise ScraperError(
                ErrorCode.CONNECTION_ERROR,
                f"Skyvern could not be reached ({exc.__class__.__name__}).",
            ) from exc
        if response.status_code in {401, 403}:
            raise ScraperError(ErrorCode.API_AUTH_REQUIRED, "Skyvern rejected the configured key.")
        if response.status_code >= 400:
            raise ScraperError(ErrorCode.HTTP_ERROR, f"Skyvern returned {response.status_code}.")

        payload = response.json()
        from .scrapegraph_engine import _records_from

        return _records_from(payload.get("output", payload))
