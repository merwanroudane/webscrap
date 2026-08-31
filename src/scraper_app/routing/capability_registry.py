"""Capability registry (audit sections AL and AQ).

Single source of truth for what the router may select and what the Settings
page shows. The rule that governs this file: **a provider is only listed as
Ready when a real adapter exists, its package imports, and its credentials are
present.** Nothing here is aspirational.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from ..config import has_credentials
from ..engines.agentic_engines import BrowserUseEngine, SkyvernEngine, StagehandEngine
from ..engines.agentql_engine import AgentQLEngine
from ..engines.base import BaseEngine
from ..engines.crawl4ai_engine import Crawl4aiEngine
from ..engines.crawler_engines import CrawleeEngine, ScrapyEngine, SeleniumEngine
from ..engines.direct_file import DirectFileEngine
from ..engines.document_engine import DocumentEngine
from ..engines.firecrawl_engine import FirecrawlEngine
from ..engines.html_engine import (
    FeedEngine,
    LinksEngine,
    RepeatedDomEngine,
    StructuredDataEngine,
)
from ..engines.json_engine import JsonApiEngine
from ..engines.playwright_engine import PlaywrightEngine
from ..engines.provider_engines import ManagedFetchEngine, SemanticContentEngine
from ..engines.scrapegraph_engine import ScrapeGraphEngine
from ..engines.scrapling_engine import ScraplingEngine
from ..engines.table_engine import TableEngine
from ..engines.trafilatura_engine import ArticleEngine


@lru_cache(maxsize=1)
def engine_instances() -> dict[str, BaseEngine]:
    """Every engine the router may select, keyed by name."""
    engines: list[BaseEngine] = [
        # Tier 0-1 — deterministic, free, local. Always preferred.
        DirectFileEngine(),
        JsonApiEngine(),
        TableEngine(),
        RepeatedDomEngine(),
        StructuredDataEngine(),
        FeedEngine(),
        LinksEngine(),
        ArticleEngine(),
        DocumentEngine(),
        # Tier 2 — crawler frameworks.
        ScrapyEngine(),
        CrawleeEngine(),
        # Tier 3 — browsers.
        PlaywrightEngine(),
        SeleniumEngine(),
        ScraplingEngine(),
        # Tier 4 — adaptive/semantic and managed providers.
        Crawl4aiEngine(),
        FirecrawlEngine(),
        ScrapeGraphEngine(),
        AgentQLEngine(),
        ManagedFetchEngine(),
        SemanticContentEngine(),
        # Tier 5 — agentic, last resort.
        StagehandEngine(),
        BrowserUseEngine(),
        SkyvernEngine(),
    ]
    return {engine.name: engine for engine in engines}


def get_engine(name: str) -> BaseEngine | None:
    return engine_instances().get(name)


@dataclass
class ProviderInfo:
    """One row of the Settings → Engines table."""

    name: str
    label: str
    type: str  # local | local browser | cloud | document | agentic | crawler
    cost_mode: str
    implemented: bool
    package: str | None = None
    credential: str | None = None
    install_hint: str = ""
    docs: str = ""
    notes: str = ""

    def status(self) -> tuple[str, str]:
        """``(state, detail)`` where state is ready/optional/not_configured/catalogue."""
        if not self.implemented:
            return "catalogue", "Known provider — adapter not implemented in this version."

        engine = get_engine(self.name)
        if engine is not None:
            availability = engine.availability()
            if availability.ready:
                return "ready", availability.reason or "Available now."
            reason = availability.reason.lower()
            if "key" in reason or "credential" in reason or "configured" in reason:
                return "not_configured", availability.reason
            return "optional", availability.reason

        if self.package:
            try:
                __import__(self.package)
            except Exception:
                return "optional", "Optional package not installed."
        if self.credential and not has_credentials(self.credential):
            return "not_configured", "API key not configured."
        return "ready", "Available now."


BUILT_IN_PROVIDERS: list[ProviderInfo] = [
    # ------------------------------------------------------------ deterministic
    ProviderInfo(
        "direct_file",
        "Direct data file",
        "local",
        "free",
        True,
        docs="https://pandas.pydata.org/",
        notes="CSV/TSV/JSON/JSONL/Excel/Parquet/Feather/Stata/SPSS/ZIP.",
    ),
    ProviderInfo(
        "json_api",
        "Direct JSON API",
        "local",
        "free",
        True,
        docs="https://www.python-httpx.org/",
        notes="Preferred whenever a public endpoint is observed.",
    ),
    ProviderInfo(
        "table",
        "HTML table",
        "local",
        "free",
        True,
        docs="https://pandas.pydata.org/docs/reference/api/pandas.read_html.html",
    ),
    ProviderInfo(
        "repeated_dom", "Repeated page structure", "local", "free", True, docs="https://lxml.de/"
    ),
    ProviderInfo(
        "structured",
        "Structured metadata",
        "local",
        "free",
        True,
        package="extruct",
        docs="https://github.com/scrapinghub/extruct",
    ),
    ProviderInfo(
        "feed",
        "RSS/Atom feed",
        "local",
        "free",
        True,
        package="feedparser",
        docs="https://github.com/kurtmckee/feedparser",
    ),
    ProviderInfo("links", "Links and files", "local", "free", True),
    ProviderInfo(
        "article",
        "Article / main text",
        "local",
        "free",
        True,
        package="trafilatura",
        docs="https://github.com/adbar/trafilatura",
    ),
    ProviderInfo(
        "document",
        "Document (PDF)",
        "document",
        "local_compute",
        True,
        install_hint="pip install pymupdf   (or docling)",
        docs="https://github.com/pymupdf/PyMuPDF",
        notes="PyMuPDF and Docling are both AGPL-3.0 — optional by design.",
    ),
    # ---------------------------------------------------------------- crawlers
    ProviderInfo(
        "scrapy",
        "Scrapy crawler",
        "crawler",
        "free",
        True,
        package="scrapy",
        install_hint="pip install scrapy",
        docs="https://github.com/scrapy/scrapy",
        notes="Bounded multi-page crawls through Scrapy's scheduler.",
    ),
    ProviderInfo(
        "crawlee",
        "Crawlee crawler",
        "crawler",
        "free",
        True,
        package="crawlee",
        install_hint="pip install crawlee",
        docs="https://github.com/apify/crawlee-python",
    ),
    # ---------------------------------------------------------------- browsers
    ProviderInfo(
        "playwright",
        "Browser rendering",
        "local browser",
        "local_compute",
        True,
        package="playwright",
        install_hint="pip install playwright && playwright install chromium",
        docs="https://github.com/microsoft/playwright-python",
        notes="Also drives Browserbase/Hyperbrowser/Steel/Browserless when configured.",
    ),
    ProviderInfo(
        "selenium",
        "Selenium (compatibility)",
        "local browser",
        "local_compute",
        True,
        package="selenium",
        install_hint="pip install selenium",
        docs="https://github.com/SeleniumHQ/selenium",
        notes="Fallback only; Playwright is the default browser.",
    ),
    ProviderInfo(
        "scrapling",
        "Scrapling (adaptive)",
        "local",
        "local_compute",
        True,
        package="scrapling",
        install_hint="pip install 'scrapling[fetchers]' && scrapling install",
        docs="https://github.com/D4Vinci/Scrapling",
        notes="Relocates selectors after a site redesign.",
    ),
    # ------------------------------------------------------- adaptive / managed
    ProviderInfo(
        "crawl4ai",
        "Crawl4AI",
        "local",
        "local_compute",
        True,
        package="crawl4ai",
        install_hint="pip install crawl4ai && crawl4ai-setup",
        docs="https://github.com/unclecode/crawl4ai",
        notes="DOM mode by default; semantic mode only when AI is enabled.",
    ),
    ProviderInfo(
        "firecrawl",
        "Firecrawl",
        "cloud",
        "metered",
        True,
        package="firecrawl",
        credential="firecrawl",
        install_hint="pip install firecrawl-py",
        docs="https://github.com/firecrawl/firecrawl",
        notes="Scrape, crawl, map and search. Extract is not in the current SDK.",
    ),
    ProviderInfo(
        "scrapegraph",
        "ScrapeGraphAI",
        "cloud",
        "metered",
        True,
        package="scrapegraph_py",
        credential="scrapegraph",
        install_hint="pip install 'scrapegraph-py>=2.1.0'",
        docs="https://github.com/ScrapeGraphAI/scrapegraph-py",
    ),
    ProviderInfo(
        "agentql",
        "AgentQL",
        "cloud",
        "metered",
        True,
        credential="agentql",
        install_hint="Set AGENTQL_API_KEY (REST API; the SDK is optional)",
        docs="https://docs.agentql.com/",
    ),
    ProviderInfo(
        "managed_fetch",
        "Managed fetch providers",
        "cloud",
        "metered",
        True,
        install_hint="Add a key such as ZENROWS_API_KEY or SCRAPINGBEE_API_KEY",
        docs="https://docs.zenrows.com/",
        notes="ZenRows · ScrapingBee · ScraperAPI · ScrapingAnt · Scrapfly · "
        "Oxylabs · Bright Data · Scrapeless · Nimble · Thordata.",
    ),
    ProviderInfo(
        "semantic_content",
        "Semantic content providers",
        "cloud",
        "metered",
        True,
        install_hint="Add DIFFBOT_TOKEN or JINA_API_KEY",
        docs="https://docs.diffbot.com/",
        notes="Diffbot and Jina Reader, for prose-heavy pages.",
    ),
    # ----------------------------------------------------------------- agentic
    ProviderInfo(
        "stagehand",
        "Stagehand",
        "agentic",
        "metered",
        True,
        package="stagehand",
        install_hint="pip install stagehand",
        docs="https://github.com/browserbase/stagehand",
        notes="Multi-step public workflows only.",
    ),
    ProviderInfo(
        "browser_use",
        "Browser Use",
        "agentic",
        "metered",
        True,
        package="browser_use",
        install_hint="pip install browser-use",
        docs="https://github.com/browser-use/browser-use",
        notes="Needs a model key; last resort in routing.",
    ),
    ProviderInfo(
        "skyvern",
        "Skyvern",
        "agentic",
        "metered",
        True,
        credential="skyvern",
        install_hint="Set SKYVERN_API_KEY",
        docs="https://github.com/Skyvern-AI/skyvern",
    ),
]

#: Providers that are known but genuinely not integrated here, each with a
#: reason. Kept short on purpose: everything feasible has been implemented.
CATALOGUE_PROVIDERS: list[ProviderInfo] = [
    ProviderInfo(
        "apify",
        "Apify",
        "cloud",
        "metered",
        False,
        package="apify",
        docs="https://github.com/apify/apify-sdk-python",
        notes="Actor-based platform: each actor has its own input schema, so a generic "
        "adapter would misrepresent it. Use Crawlee locally, or call a specific actor.",
    ),
    ProviderInfo(
        "zyte",
        "Zyte API",
        "cloud",
        "metered",
        False,
        package="zyte_api",
        docs="https://github.com/zytedata/python-zyte-api",
        notes="Overlaps entirely with the managed fetch providers already implemented; "
        "left out to avoid a redundant metered path.",
    ),
]


def all_providers() -> list[ProviderInfo]:
    return [*BUILT_IN_PROVIDERS, *CATALOGUE_PROVIDERS]


@dataclass
class EngineStatusRow:
    name: str
    label: str
    type: str
    state: str
    detail: str
    cost_mode: str
    install_hint: str = ""
    docs: str = ""
    notes: str = ""
    order: int = field(default=0)


def engine_status_table() -> list[EngineStatusRow]:
    """Rows for the Settings → Engines page, readiest first."""
    rows: list[EngineStatusRow] = []
    state_order = {"ready": 0, "not_configured": 1, "optional": 2, "catalogue": 3, "blocked": 4}
    for provider in all_providers():
        state, detail = provider.status()
        rows.append(
            EngineStatusRow(
                name=provider.name,
                label=provider.label,
                type=provider.type,
                state=state,
                detail=detail,
                cost_mode=provider.cost_mode,
                install_hint=provider.install_hint,
                docs=provider.docs,
                notes=provider.notes,
                order=state_order.get(state, 5),
            )
        )
    rows.sort(key=lambda row: (row.order, row.label.lower()))
    return rows


def ready_engine_names() -> list[str]:
    return [name for name, engine in engine_instances().items() if engine.available()]


def engines_by_capability(capability: str) -> list[BaseEngine]:
    return [engine for engine in engine_instances().values() if capability in engine.capabilities]
