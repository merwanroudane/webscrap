"""Capability registry (spec sections 56 and 105).

Two things live here:

1. the *implemented* engines the router can actually select;
2. an honest catalogue of the wider provider ecosystem, marked
   ``implemented=False`` so the Settings page can tell the researcher exactly
   what exists, what is installed, and what is merely known about.

No fake adapters, no placeholder buttons that pretend to work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from ..config import has_credentials
from ..engines.base import BaseEngine
from ..engines.crawl4ai_engine import Crawl4aiEngine
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
from ..engines.table_engine import TableEngine
from ..engines.trafilatura_engine import ArticleEngine


@lru_cache(maxsize=1)
def engine_instances() -> dict[str, BaseEngine]:
    """Every engine the router may select, keyed by name."""
    engines: list[BaseEngine] = [
        DirectFileEngine(),
        JsonApiEngine(),
        TableEngine(),
        RepeatedDomEngine(),
        StructuredDataEngine(),
        FeedEngine(),
        LinksEngine(),
        ArticleEngine(),
        DocumentEngine(),
        PlaywrightEngine(),
        Crawl4aiEngine(),
        FirecrawlEngine(),
    ]
    return {engine.name: engine for engine in engines}


def get_engine(name: str) -> BaseEngine | None:
    return engine_instances().get(name)


@dataclass
class ProviderInfo:
    """One row of the Settings → Engines table."""

    name: str
    label: str
    type: str  # local | local browser | cloud | document | discovery
    cost_mode: str
    implemented: bool
    package: str | None = None
    credential: str | None = None
    install_hint: str = ""
    docs: str = ""
    notes: str = ""

    def status(self) -> tuple[str, str]:
        """Return ``(state, detail)`` where state is ready/optional/catalogue."""
        if not self.implemented:
            return "catalogue", "Known provider — adapter not implemented in this version."
        engine = get_engine(self.name)
        if engine is not None:
            availability = engine.availability()
            if availability.ready:
                return "ready", "Available now."
            return "optional", availability.reason
        if self.package:
            try:
                __import__(self.package)
            except Exception:
                return "optional", "Optional package not installed."
        if self.credential and not has_credentials(self.credential):
            return "optional", "API key not configured."
        return "ready", "Available now."


BUILT_IN_PROVIDERS: list[ProviderInfo] = [
    ProviderInfo("direct_file", "Direct data file", "local", "free", True,
                 docs="https://pandas.pydata.org/",
                 notes="CSV/TSV/JSON/JSONL/Excel/Parquet/Feather/Stata/SPSS/ZIP."),
    ProviderInfo("json_api", "Direct JSON API", "local", "free", True,
                 docs="https://www.python-httpx.org/",
                 notes="Preferred whenever a public endpoint is observed."),
    ProviderInfo("table", "HTML table", "local", "free", True,
                 docs="https://pandas.pydata.org/docs/reference/api/pandas.read_html.html"),
    ProviderInfo("repeated_dom", "Repeated page structure", "local", "free", True,
                 docs="https://lxml.de/"),
    ProviderInfo("structured", "Structured metadata", "local", "free", True,
                 package="extruct", docs="https://github.com/scrapinghub/extruct"),
    ProviderInfo("feed", "RSS/Atom feed", "local", "free", True,
                 package="feedparser", docs="https://github.com/kurtmckee/feedparser"),
    ProviderInfo("links", "Links and files", "local", "free", True),
    ProviderInfo("article", "Article / main text", "local", "free", True,
                 package="trafilatura", docs="https://github.com/adbar/trafilatura"),
    ProviderInfo("document", "Document (PDF)", "document", "local_compute", True,
                 package="fitz", install_hint="pip install pymupdf",
                 docs="https://github.com/pymupdf/PyMuPDF"),
    ProviderInfo("playwright", "Browser rendering", "local browser", "local_compute", True,
                 package="playwright",
                 install_hint="pip install playwright && playwright install chromium",
                 docs="https://github.com/microsoft/playwright-python"),
    ProviderInfo("crawl4ai", "Crawl4AI", "local", "local_compute", True,
                 package="crawl4ai", install_hint="pip install crawl4ai && crawl4ai-setup",
                 docs="https://github.com/unclecode/crawl4ai"),
    ProviderInfo("firecrawl", "Firecrawl", "cloud", "metered", True,
                 package="firecrawl", credential="firecrawl",
                 install_hint="pip install firecrawl-py",
                 docs="https://github.com/firecrawl/firecrawl"),
]

#: Ecosystem catalogue (spec sections 95-105). Listed honestly as not implemented.
CATALOGUE_PROVIDERS: list[ProviderInfo] = [
    ProviderInfo("scrapling", "Scrapling", "local", "local_compute", False,
                 package="scrapling", install_hint="pip install scrapling[fetchers]",
                 docs="https://github.com/D4Vinci/Scrapling"),
    ProviderInfo("scrapy", "Scrapy", "local", "free", False, package="scrapy",
                 docs="https://github.com/scrapy/scrapy"),
    ProviderInfo("crawlee", "Crawlee for Python", "local", "free", False, package="crawlee",
                 docs="https://github.com/apify/crawlee-python"),
    ProviderInfo("selenium", "Selenium", "local browser", "local_compute", False,
                 package="selenium", docs="https://github.com/SeleniumHQ/selenium"),
    ProviderInfo("scrapegraph", "ScrapeGraphAI", "cloud", "metered", False,
                 package="scrapegraph_py", credential="scrapegraph",
                 docs="https://github.com/ScrapeGraphAI/scrapegraph-py"),
    ProviderInfo("agentql", "AgentQL", "cloud", "metered", False, package="agentql",
                 credential="agentql", docs="https://github.com/tinyfish-io/agentql"),
    ProviderInfo("stagehand", "Stagehand", "cloud browser", "metered", False,
                 package="stagehand", docs="https://github.com/browserbase/stagehand"),
    ProviderInfo("browser_use", "Browser Use", "agentic", "metered", False,
                 package="browser_use", credential="browser_use",
                 docs="https://github.com/browser-use/browser-use"),
    ProviderInfo("skyvern", "Skyvern", "agentic", "metered", False, package="skyvern",
                 credential="skyvern", docs="https://github.com/Skyvern-AI/skyvern"),
    ProviderInfo("browserbase", "Browserbase", "cloud browser", "metered", False,
                 credential="browserbase", docs="https://www.browserbase.com/"),
    ProviderInfo("apify", "Apify", "cloud", "metered", False, package="apify",
                 credential="apify", docs="https://github.com/apify/apify-sdk-python"),
    ProviderInfo("zyte", "Zyte API", "cloud", "metered", False, package="zyte_api",
                 credential="zyte", docs="https://github.com/zytedata/python-zyte-api"),
    ProviderInfo("docling", "Docling", "document", "local_compute", False, package="docling",
                 install_hint="pip install docling", docs="https://github.com/docling-project/docling"),
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
    """Rows for the Settings → Engines page."""
    rows: list[EngineStatusRow] = []
    state_order = {"ready": 0, "optional": 1, "catalogue": 2}
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
                order=state_order.get(state, 3),
            )
        )
    rows.sort(key=lambda row: (row.order, row.label.lower()))
    return rows


def ready_engine_names() -> list[str]:
    return [name for name, engine in engine_instances().items() if engine.available()]
