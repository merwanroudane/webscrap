"""Crawler-framework engines (audit sections J and K).

* :class:`ScrapyEngine`   — bounded multi-page crawls with Scrapy's scheduler.
* :class:`CrawleeEngine`  — the same job through Crawlee's request queue.
* :class:`SeleniumEngine` — compatibility fallback only; Playwright stays the
  default local browser.

All three reuse the existing deterministic extractors on whatever HTML they
retrieve, so a page produces the same columns regardless of which engine
fetched it. All three are optional and bounded by the same crawl limits.
"""

from __future__ import annotations

import time
from typing import Any

from ..config import SETTINGS
from ..exceptions import ErrorCode, ScraperError
from ..logging_config import RunLogger
from ..models import CandidateDataset, ExtractionRequest, ExtractionResult, ExtractionSchema
from ..security.url_guard import guard_url, is_allowed
from .base import Availability, BaseEngine, detect_schema_drift


def rows_from_html(
    html: str, url: str, selector: str | None, table_index: int | None
) -> list[dict[str, Any]]:
    """Deterministic extraction shared by every crawler engine."""
    from ..discovery import repeated_patterns, table_detector

    if table_index is not None:
        _candidates, frames = table_detector.detect_tables(html, url)
        if int(table_index) < len(frames):
            return frames[int(table_index)].to_dict(orient="records")
        return []
    if selector:
        return repeated_patterns.extract_rows_with_selector(html, selector, [], url)

    _candidates, frames = table_detector.detect_tables(html, url)
    if frames:
        return frames[0].to_dict(orient="records")
    patterns = repeated_patterns.detect_repeated_patterns(html, url)
    if patterns:
        return repeated_patterns.extract_rows_with_selector(
            html, patterns[0].selector, patterns[0].fields, url
        )
    return []


def target_urls(request: ExtractionRequest, candidate: CandidateDataset | None) -> list[str]:
    """Build the bounded URL list for a crawl."""
    payload = (candidate.payload if candidate else {}) or {}
    urls: list[str] = [str(u) for u in payload.get("urls", []) if u]
    if not urls:
        plan = request.pagination
        if plan.url_template and "{page}" in plan.url_template:
            pages = min(request.max_pages or 1, SETTINGS.limits.hard_max_pages)
            urls = [
                plan.url_template.replace("{page}", str(plan.start + index * max(plan.step, 1)))
                for index in range(pages)
            ]
        else:
            urls = [request.url]
    return [u for u in dict.fromkeys(urls) if is_allowed(u)][: SETTINGS.limits.hard_max_pages]


class _CrawlerEngineBase(BaseEngine):
    """Shared assembly of crawler results."""

    def _assemble(
        self,
        request: ExtractionRequest,
        pages: list[tuple[str, str]],
        candidate: CandidateDataset | None,
        started: float,
        logger: RunLogger | None,
        metadata: dict[str, Any],
    ) -> ExtractionResult:
        payload = (candidate.payload if candidate else {}) or {}
        selector = request.selector or payload.get("selector")
        table_index = payload.get("table_index")

        records: list[dict[str, Any]] = []
        drift: list[str] = []
        baseline: list[str] = []
        warnings: list[str] = []

        for number, (url, html) in enumerate(pages, start=1):
            page_rows = rows_from_html(html, url, selector, table_index)
            if not page_rows:
                warnings.append(f"No rows found on {url}")
                continue
            if not baseline:
                baseline = list(page_rows[0].keys())
            else:
                drift.extend(detect_schema_drift(page_rows, baseline))
            if request.add_provenance_columns:
                for row in page_rows:
                    row.setdefault("_source_url", url)
                    row.setdefault("_source_page", number)
            records.extend(page_rows)

        if not records:
            raise ScraperError(
                ErrorCode.NO_DATA_DETECTED,
                f"{self.label} fetched {len(pages)} page(s) but found no extractable rows.",
            )

        max_rows = request.max_rows or SETTINGS.limits.max_rows
        truncated = len(records) > max_rows
        records = records[:max_rows]

        if logger:
            logger.log(
                self.name, "crawl_complete", engine=self.name, pages=len(pages), rows=len(records)
            )

        return self._result(
            success=True,
            records=records,
            columns=list(dict.fromkeys(key for record in records for key in record)),
            source_urls=[url for url, _html in pages],
            started=started,
            pages_requested=len(pages),
            pages_successful=len(pages),
            truncated=truncated,
            warnings=warnings[:10],
            schema_drift=list(dict.fromkeys(drift))[:10],
            metadata=metadata,
        )


class ScrapyEngine(_CrawlerEngineBase):
    """Bounded crawl through Scrapy's scheduler (optional)."""

    name = "scrapy"
    label = "Scrapy crawler"
    capabilities = {"static_html", "crawl", "pagination", "local"}
    tier = 2
    cost_mode = "free"
    reliability = 0.85
    speed = 0.75
    requires_package = "scrapy"

    def availability(self) -> Availability:
        try:
            import scrapy  # noqa: F401
        except Exception:
            return Availability(False, "Optional package not installed.", "pip install scrapy")
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

        urls = target_urls(request, candidate)[: (limit_pages or request.max_pages or 1)]
        for url in urls:
            guard_url(url)

        pages = self._crawl(urls, request, progress)
        return self._assemble(
            request, pages, candidate, started, logger, {"framework": "scrapy", "urls": len(urls)}
        )

    def _crawl(
        self, urls: list[str], request: ExtractionRequest, progress
    ) -> list[tuple[str, str]]:  # pragma: no cover - optional dependency
        """Run a single-process Scrapy crawl and collect (url, html)."""
        import scrapy
        from scrapy.crawler import CrawlerProcess

        collected: list[tuple[str, str]] = []
        delay = 1.0 / max(SETTINGS.politeness.requests_per_second, 0.1)

        class _CollectSpider(scrapy.Spider):
            name = "srws_collect"
            start_urls = list(urls)
            custom_settings = {
                "LOG_ENABLED": False,
                "ROBOTSTXT_OBEY": request.respect_robots,
                "DOWNLOAD_DELAY": delay,
                "CONCURRENT_REQUESTS_PER_DOMAIN": SETTINGS.politeness.concurrency_per_host,
                "USER_AGENT": SETTINGS.user_agent,
                "RETRY_TIMES": SETTINGS.politeness.max_retries,
                "DOWNLOAD_MAXSIZE": SETTINGS.limits.max_html_bytes,
                "TELNETCONSOLE_ENABLED": False,
            }

            def parse(self, response):  # noqa: D401
                collected.append((response.url, response.text))

        process = CrawlerProcess(settings={"LOG_ENABLED": False})
        process.crawl(_CollectSpider)
        process.start()  # blocks until the crawl finishes
        return collected


class CrawleeEngine(_CrawlerEngineBase):
    """Bounded crawl through Crawlee's request queue (optional)."""

    name = "crawlee"
    label = "Crawlee crawler"
    capabilities = {"static_html", "crawl", "pagination", "local"}
    tier = 2
    cost_mode = "free"
    reliability = 0.83
    speed = 0.72
    requires_package = "crawlee"

    def availability(self) -> Availability:
        try:
            import crawlee  # noqa: F401
        except Exception:
            return Availability(False, "Optional package not installed.", "pip install crawlee")
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

        urls = target_urls(request, candidate)[: (limit_pages or request.max_pages or 1)]
        for url in urls:
            guard_url(url)

        pages = self._crawl(urls)
        return self._assemble(
            request, pages, candidate, started, logger, {"framework": "crawlee", "urls": len(urls)}
        )

    def _crawl(
        self, urls: list[str]
    ) -> list[tuple[str, str]]:  # pragma: no cover - optional dependency
        import asyncio

        from crawlee.crawlers import HttpCrawler  # type: ignore

        collected: list[tuple[str, str]] = []

        async def run() -> None:
            crawler = HttpCrawler(
                max_requests_per_crawl=len(urls),
                request_handler_timeout=None,
            )

            @crawler.router.default_handler
            async def handler(context) -> None:  # noqa: ANN001
                body = await context.http_response.read()
                collected.append((context.request.url, body.decode("utf-8", errors="replace")))

            await crawler.run(urls)

        asyncio.run(run())
        return collected


class SeleniumEngine(_CrawlerEngineBase):
    """Compatibility browser path. Playwright remains the default."""

    name = "selenium"
    label = "Selenium (compatibility)"
    capabilities = {"javascript", "static_html", "local"}
    tier = 3
    cost_mode = "local_compute"
    reliability = 0.7
    speed = 0.35
    requires_package = "selenium"

    def availability(self) -> Availability:
        try:
            import selenium  # noqa: F401
        except Exception:
            return Availability(False, "Optional package not installed.", "pip install selenium")
        return Availability(
            True,
            "Selenium is a compatibility fallback; Playwright is preferred for browser rendering.",
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
        if not request.allow_browser:
            raise ScraperError(ErrorCode.NO_ROUTE, "Browser mode is switched off for this run.")

        guarded = guard_url(request.url)
        html = self._render(guarded.url, request.wait_for)
        return self._assemble(
            request, [(guarded.url, html)], candidate, started, logger, {"browser": "selenium"}
        )

    def _render(self, url: str, wait_for: str | None) -> str:  # pragma: no cover - needs a browser
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument(f"--user-agent={SETTINGS.user_agent}")

        driver = webdriver.Chrome(options=options)
        try:
            driver.set_page_load_timeout(SETTINGS.limits.browser_timeout)
            driver.get(url)
            if wait_for:
                WebDriverWait(driver, min(SETTINGS.limits.browser_timeout, 20)).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, wait_for))
                )
            return driver.page_source
        finally:
            driver.quit()
