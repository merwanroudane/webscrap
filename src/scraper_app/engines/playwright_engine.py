"""Playwright browser engine (Tier 3).

Used only when the static HTML does not contain the data: it renders the page,
optionally clicks a load-more button or scrolls for infinite lists, then hands
the rendered DOM to the same deterministic table/repeated-pattern extractors.

If the network probe finds a stable JSON endpoint the router prefers that
instead — browser rendering is the fallback, not the goal.
"""

from __future__ import annotations

import time
from typing import Any

from ..config import SETTINGS
from ..discovery import repeated_patterns, table_detector
from ..discovery.network_probe import playwright_available
from ..exceptions import ErrorCode, ScraperError
from ..logging_config import RunLogger
from ..models import (
    CandidateDataset,
    EngineProbe,
    ExtractionRequest,
    ExtractionResult,
    ExtractionSchema,
    FieldSpec,
    PaginationType,
)
from ..security.url_guard import guard_url
from .base import BaseEngine


class PlaywrightEngine(BaseEngine):
    name = "playwright"
    label = "Browser rendering"
    capabilities = {"javascript", "static_html", "html_tables", "network_capture", "pagination", "local"}
    tier = 3
    cost_mode = "local_compute"
    reliability = 0.8
    speed = 0.4
    requires_package = "playwright"

    def availability(self):
        from .base import Availability

        ok, reason = playwright_available()
        if ok:
            return Availability(True)
        return Availability(
            False,
            reason,
            "pip install playwright && playwright install chromium",
        )

    def probe(
        self, request: ExtractionRequest, candidate: CandidateDataset | None = None
    ) -> EngineProbe:
        status = self.availability()
        return EngineProbe(
            engine=self.name,
            available=status.ready,
            good_enough=status.ready,
            score=0.75 if status.ready else 0.0,
            reason=status.reason or "Renders JavaScript before extracting.",
        )

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

        payload = (candidate.payload if candidate else {}) or {}
        guarded = guard_url(request.url)
        plan = request.pagination
        max_pages = min(limit_pages or request.max_pages or 1, SETTINGS.limits.hard_max_pages)

        pages_html = self._render(
            guarded.url,
            wait_for=request.wait_for,
            plan_type=plan.type,
            next_selector=plan.next_selector,
            max_pages=max_pages,
            progress=progress,
            logger=logger,
        )

        records: list[dict[str, Any]] = []
        columns: list[str] = []
        selector = request.selector or payload.get("selector")
        table_index = payload.get("table_index")
        fields = [FieldSpec(**f) for f in payload.get("fields", [])] if payload.get("fields") else []

        for page_number, (url, html) in enumerate(pages_html, start=1):
            page_records: list[dict[str, Any]] = []
            if table_index is not None:
                _cands, frames = table_detector.detect_tables(html, url)
                if int(table_index) < len(frames):
                    frame = frames[int(table_index)]
                    page_records = frame.to_dict(orient="records")
                    columns = columns or [str(c) for c in frame.columns]
            elif selector:
                page_records = repeated_patterns.extract_rows_with_selector(html, selector, fields, url)
            else:
                detected = repeated_patterns.detect_repeated_patterns(html, url)
                if detected:
                    selector = detected[0].selector
                    fields = fields or detected[0].fields
                    page_records = repeated_patterns.extract_rows_with_selector(
                        html, selector, fields, url
                    )
                else:
                    _cands, frames = table_detector.detect_tables(html, url)
                    if frames:
                        table_index = 0
                        page_records = frames[0].to_dict(orient="records")
                        columns = columns or [str(c) for c in frames[0].columns]

            if request.add_provenance_columns:
                for record in page_records:
                    record.setdefault("_source_url", url)
                    record.setdefault("_source_page", page_number)
            records.extend(page_records)

        if not records:
            raise ScraperError(
                ErrorCode.NO_DATA_DETECTED,
                "The rendered page did not contain a recognisable table or repeated structure.",
            )

        max_rows = request.max_rows or SETTINGS.limits.max_rows
        truncated = len(records) > max_rows
        records = records[:max_rows]

        return self._result(
            success=True,
            records=records,
            columns=columns or list(dict.fromkeys(key for record in records for key in record)),
            source_urls=[url for url, _html in pages_html],
            started=started,
            pages_requested=len(pages_html),
            pages_successful=len(pages_html),
            truncated=truncated,
            metadata={"selector": selector, "table_index": table_index, "rendered": True},
        )

    # ------------------------------------------------------------------ browser
    def _render(
        self,
        url: str,
        *,
        wait_for: str | None,
        plan_type: PaginationType,
        next_selector: str | None,
        max_pages: int,
        progress=None,
        logger: RunLogger | None = None,
    ) -> list[tuple[str, str]]:
        from playwright.sync_api import sync_playwright

        timeout_ms = int(SETTINGS.limits.browser_timeout * 1000)
        pages: list[tuple[str, str]] = []

        try:  # pragma: no cover - requires a real browser
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(user_agent=SETTINGS.user_agent)
                page = context.new_page()
                page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                try:
                    page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 15000))
                except Exception:
                    pass
                if wait_for:
                    try:
                        page.wait_for_selector(wait_for, timeout=min(timeout_ms, 15000))
                    except Exception as exc:
                        raise ScraperError(
                            ErrorCode.SELECTOR_NOT_FOUND,
                            f"The element {wait_for!r} never appeared.",
                        ) from exc

                if plan_type == PaginationType.INFINITE_SCROLL:
                    self._scroll(page, max_pages, logger)
                    pages.append((page.url, page.content()))
                elif plan_type == PaginationType.LOAD_MORE and next_selector:
                    self._load_more(page, next_selector, max_pages, logger)
                    pages.append((page.url, page.content()))
                elif plan_type in {PaginationType.NEXT_BUTTON, PaginationType.NEXT_LINK} and max_pages > 1:
                    for index in range(max_pages):
                        if progress:
                            progress(index + 1, max_pages, page.url)
                        pages.append((page.url, page.content()))
                        selector = next_selector or "a[rel=next], a.next, button.next"
                        try:
                            locator = page.locator(selector).first
                            if locator.count() == 0 or not locator.is_enabled():
                                break
                            locator.click(timeout=8000)
                            page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
                            page.wait_for_timeout(600)
                        except Exception:
                            break
                else:
                    pages.append((page.url, page.content()))

                context.close()
                browser.close()
        except ScraperError:
            raise
        except Exception as exc:
            raise ScraperError(
                ErrorCode.INTERNAL, f"The browser session failed ({exc.__class__.__name__})."
            ) from exc

        if logger:
            logger.log("playwright", "render_complete", url=url, engine=self.name, pages=len(pages))
        return pages

    def _scroll(self, page, max_cycles: int, logger: RunLogger | None) -> None:  # pragma: no cover
        cycles = min(max(max_cycles, 1), SETTINGS.limits.max_scrolls)
        previous_height = 0
        stable = 0
        for _ in range(cycles):
            page.mouse.wheel(0, 25000)
            page.wait_for_timeout(900)
            height = page.evaluate("document.body.scrollHeight")
            if height == previous_height:
                stable += 1
                if stable >= 2:
                    break
            else:
                stable = 0
            previous_height = height

    def _load_more(self, page, selector: str, max_clicks: int, logger: RunLogger | None) -> None:  # pragma: no cover
        for _ in range(min(max_clicks, SETTINGS.limits.max_scrolls)):
            try:
                locator = page.locator(selector).first
                if locator.count() == 0 or not locator.is_visible():
                    break
                locator.click(timeout=8000)
                page.wait_for_timeout(1000)
            except Exception:
                break
