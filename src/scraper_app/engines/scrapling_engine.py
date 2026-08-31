"""Scrapling adapter (audit section I).

Scrapling is local and free. Its value here is *adaptive* parsing: when a
selector that worked yesterday stops matching because the site changed markup,
Scrapling can relocate the same elements by similarity instead of returning
nothing.

That makes it the natural fallback after a fragile deterministic selector, and
a way to re-run a saved recipe against a site that has since been redesigned.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urljoin

from ..config import SETTINGS
from ..exceptions import ErrorCode, ScraperError
from ..logging_config import RunLogger
from ..models import CandidateDataset, ExtractionRequest, ExtractionResult, ExtractionSchema
from ..security.url_guard import guard_url
from .base import Availability, BaseEngine


def _import_fetchers():
    """Return ``(Fetcher, DynamicFetcher)`` across Scrapling layouts."""
    try:  # current layout
        from scrapling.fetchers import Fetcher  # type: ignore

        try:
            from scrapling.fetchers import DynamicFetcher  # type: ignore
        except Exception:  # older name
            try:
                from scrapling.fetchers import PlayWrightFetcher as DynamicFetcher  # type: ignore
            except Exception:
                DynamicFetcher = None  # type: ignore[assignment]
        return Fetcher, DynamicFetcher
    except Exception:
        pass
    # Pre-0.3 layout exposed the fetchers at the package root.
    from scrapling import Fetcher  # type: ignore

    try:
        from scrapling import PlayWrightFetcher as DynamicFetcher  # type: ignore
    except Exception:
        DynamicFetcher = None  # type: ignore[assignment]
    return Fetcher, DynamicFetcher


class ScraplingEngine(BaseEngine):
    name = "scrapling"
    label = "Scrapling (adaptive)"
    capabilities = {"static_html", "javascript", "pagination", "local"}
    tier = 3
    cost_mode = "local_compute"
    deterministic = False  # adaptive relocation is heuristic, not deterministic
    reliability = 0.74
    speed = 0.7
    requires_package = "scrapling"

    def availability(self) -> Availability:
        try:
            _import_fetchers()
        except Exception:
            return Availability(
                False,
                "Optional package not installed.",
                "pip install 'scrapling[fetchers]' && scrapling install",
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
        payload = (candidate.payload if candidate else {}) or {}
        selector = request.selector or payload.get("selector")

        page = self._fetch(
            guarded.url, use_browser=request.allow_browser and bool(request.wait_for)
        )
        records = self._rows(page, selector, guarded.url)

        if not records:
            # Fall back to the deterministic detectors over Scrapling's HTML.
            html = getattr(page, "html_content", None) or getattr(page, "body", "") or str(page)
            records = self._deterministic_rows(str(html), guarded.url)

        if not records:
            raise ScraperError(
                ErrorCode.NO_DATA_DETECTED, "Scrapling did not find repeated content on this page."
            )

        if request.add_provenance_columns:
            for record in records:
                record.setdefault("_source_url", guarded.url)

        max_rows = request.max_rows or SETTINGS.limits.max_rows
        truncated = len(records) > max_rows
        records = records[:max_rows]

        if logger:
            logger.log(
                "scrapling",
                "extract_complete",
                url=guarded.url,
                engine=self.name,
                rows=len(records),
            )

        return self._result(
            success=True,
            records=records,
            columns=list(dict.fromkeys(key for record in records for key in record)),
            source_urls=[guarded.url],
            started=started,
            pages_requested=1,
            pages_successful=1,
            truncated=truncated,
            metadata={"selector": selector, "adaptive": True},
        )

    # ------------------------------------------------------------------ helpers
    def _fetch(self, url: str, use_browser: bool = False):  # pragma: no cover - optional dependency
        fetcher, dynamic = _import_fetchers()
        headers = {"User-Agent": SETTINGS.user_agent}
        if use_browser and dynamic is not None:
            try:
                return dynamic.fetch(url, headless=True)
            except Exception:
                pass
        try:
            return fetcher.get(url, headers=headers, timeout=SETTINGS.limits.http_timeout)
        except TypeError:
            return fetcher.get(url)

    def _rows(self, page: Any, selector: str | None, base_url: str) -> list[dict[str, Any]]:
        """Use Scrapling's adaptive selection when a selector is known."""
        if not selector:
            return []
        try:  # pragma: no cover - optional dependency
            try:
                nodes = page.css(selector, adaptive=True)
            except TypeError:
                try:
                    nodes = page.css(selector, auto_match=True)
                except TypeError:
                    nodes = page.css(selector)
        except Exception:
            return []

        records: list[dict[str, Any]] = []
        for node in nodes or []:
            row: dict[str, Any] = {}
            try:
                heading = node.css("h1, h2, h3, h4, h5")
                if heading:
                    row["title"] = " ".join(str(heading[0].text).split())
                link = node.css("a::attr(href)")
                if link:
                    href = str(link[0])
                    row["link"] = urljoin(base_url, href)
                text = " ".join(str(node.text).split())
                if not row and text:
                    row["text"] = text[:400]
                elif text:
                    row.setdefault("text", text[:400])
            except Exception:
                continue
            if row:
                records.append(row)
        return records

    def _deterministic_rows(self, html: str, base_url: str) -> list[dict[str, Any]]:
        from ..discovery import repeated_patterns, table_detector

        _candidates, frames = table_detector.detect_tables(html, base_url)
        if frames:
            return frames[0].to_dict(orient="records")
        patterns = repeated_patterns.detect_repeated_patterns(html, base_url)
        if patterns:
            return repeated_patterns.extract_rows_with_selector(
                html, patterns[0].selector, patterns[0].fields, base_url
            )
        return []
