"""Single source of truth for every credential and setting (audit v0.2 §17-25).

Before this module the same fact lived in three places — ``PROVIDER_ENV_KEYS``
in config, ``env_keys`` on each provider descriptor, and ``.env.example`` — and
they drifted: twenty provider keys were readable by the code but documented
nowhere, so a provider looked unconfigurable.

Everything is declared here once. ``.env.example`` is generated from it, the
capability registry reads it, and a test fails the build if the file and the
code disagree.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class CredentialSpec:
    """One provider's credential requirement."""

    id: str
    label: str
    category: str
    env_vars: tuple[str, ...]
    docs: str = ""
    optional_vars: tuple[str, ...] = ()
    note: str = ""

    def configured(self) -> bool:
        return bool(self.env_vars) and all(os.getenv(v, "").strip() for v in self.env_vars)

    def missing(self) -> list[str]:
        return [v for v in self.env_vars if not os.getenv(v, "").strip()]


@dataclass(frozen=True)
class SettingSpec:
    """One non-secret behaviour setting."""

    name: str
    description: str
    default: str = ""


# --------------------------------------------------------------------- AI models
AI_CREDENTIALS: tuple[CredentialSpec, ...] = (
    CredentialSpec(
        "anthropic",
        "Anthropic Claude",
        "AI model",
        ("ANTHROPIC_API_KEY",),
        "https://docs.anthropic.com/en/api/getting-started",
    ),
    CredentialSpec(
        "openai",
        "OpenAI",
        "AI model",
        ("OPENAI_API_KEY",),
        "https://platform.openai.com/docs/api-reference",
    ),
    CredentialSpec(
        "google",
        "Google Gemini",
        "AI model",
        ("GOOGLE_API_KEY",),
        "https://ai.google.dev/gemini-api/docs",
    ),
    CredentialSpec(
        "litellm",
        "LiteLLM",
        "AI model",
        (),
        "https://docs.litellm.ai/docs/",
        note="Routes to whichever backend key above is set.",
    ),
)

# ------------------------------------------------------------ extraction engines
ENGINE_CREDENTIALS: tuple[CredentialSpec, ...] = (
    CredentialSpec(
        "firecrawl",
        "Firecrawl",
        "Extraction engine",
        ("FIRECRAWL_API_KEY",),
        "https://github.com/firecrawl/firecrawl",
    ),
    CredentialSpec(
        "scrapegraph",
        "ScrapeGraphAI",
        "Extraction engine",
        ("SGAI_API_KEY",),
        "https://github.com/ScrapeGraphAI/scrapegraph-py",
    ),
    CredentialSpec(
        "agentql",
        "AgentQL",
        "Extraction engine",
        ("AGENTQL_API_KEY",),
        "https://docs.agentql.com/",
        note="Used through the REST API; the SDK is optional.",
    ),
)

# ------------------------------------------------------------- remote browsers
REMOTE_BROWSER_CREDENTIALS: tuple[CredentialSpec, ...] = (
    CredentialSpec(
        "browserbase",
        "Browserbase",
        "Remote browser",
        ("BROWSERBASE_API_KEY",),
        "https://docs.browserbase.com/",
        optional_vars=("BROWSERBASE_PROJECT_ID",),
    ),
    CredentialSpec(
        "hyperbrowser",
        "Hyperbrowser",
        "Remote browser",
        ("HYPERBROWSER_API_KEY",),
        "https://docs.hyperbrowser.ai/",
    ),
    CredentialSpec(
        "steel",
        "Steel",
        "Remote browser",
        ("STEEL_API_KEY",),
        "https://docs.steel.dev/",
        optional_vars=("STEEL_BASE_URL",),
    ),
    CredentialSpec(
        "browserless",
        "Browserless",
        "Remote browser",
        ("BROWSERLESS_TOKEN",),
        "https://docs.browserless.io/",
        optional_vars=("BROWSERLESS_URL",),
        note="BROWSERLESS_URL points at a self-hosted instance.",
    ),
)

# --------------------------------------------------------------- managed fetch
MANAGED_FETCH_CREDENTIALS: tuple[CredentialSpec, ...] = (
    CredentialSpec(
        "zenrows", "ZenRows", "Managed fetch", ("ZENROWS_API_KEY",), "https://docs.zenrows.com/"
    ),
    CredentialSpec(
        "scrapingbee",
        "ScrapingBee",
        "Managed fetch",
        ("SCRAPINGBEE_API_KEY",),
        "https://www.scrapingbee.com/documentation/",
    ),
    CredentialSpec(
        "scraperapi",
        "ScraperAPI",
        "Managed fetch",
        ("SCRAPERAPI_KEY",),
        "https://docs.scraperapi.com/",
    ),
    CredentialSpec(
        "scrapingant",
        "ScrapingAnt",
        "Managed fetch",
        ("SCRAPINGANT_API_KEY",),
        "https://docs.scrapingant.com/",
    ),
    CredentialSpec(
        "scrapfly",
        "Scrapfly",
        "Managed fetch",
        ("SCRAPFLY_API_KEY",),
        "https://scrapfly.io/docs/scrape-api/getting-started",
    ),
    CredentialSpec(
        "oxylabs",
        "Oxylabs",
        "Managed fetch",
        ("OXYLABS_USERNAME", "OXYLABS_PASSWORD"),
        "https://developers.oxylabs.io/scraper-apis/web-scraper-api",
    ),
    CredentialSpec(
        "brightdata",
        "Bright Data",
        "Managed fetch",
        ("BRIGHTDATA_API_TOKEN",),
        "https://docs.brightdata.com/",
        optional_vars=("BRIGHTDATA_ZONE",),
        note="BRIGHTDATA_ZONE names the Web Unlocker zone.",
    ),
    CredentialSpec(
        "scrapeless",
        "Scrapeless",
        "Managed fetch",
        ("SCRAPELESS_API_KEY",),
        "https://docs.scrapeless.com/",
    ),
    CredentialSpec(
        "nimble", "Nimble", "Managed fetch", ("NIMBLE_API_KEY",), "https://docs.nimbleway.com/"
    ),
    CredentialSpec(
        "thordata",
        "Thordata",
        "Managed fetch",
        ("THORDATA_API_KEY",),
        "https://www.thordata.com/documentation/",
        optional_vars=("THORDATA_ENDPOINT",),
    ),
)

# ------------------------------------------------- discovery + semantic content
DISCOVERY_CREDENTIALS: tuple[CredentialSpec, ...] = (
    CredentialSpec(
        "tavily", "Tavily", "Source discovery", ("TAVILY_API_KEY",), "https://docs.tavily.com/"
    ),
    CredentialSpec("exa", "Exa", "Source discovery", ("EXA_API_KEY",), "https://exa.ai/docs/"),
    CredentialSpec(
        "jina_search",
        "Jina Search",
        "Source discovery",
        ("JINA_API_KEY",),
        "https://jina.ai/reader/",
    ),
)

SEMANTIC_CREDENTIALS: tuple[CredentialSpec, ...] = (
    CredentialSpec(
        "diffbot", "Diffbot", "Semantic content", ("DIFFBOT_TOKEN",), "https://docs.diffbot.com/"
    ),
    CredentialSpec(
        "jina_reader",
        "Jina Reader",
        "Semantic content",
        ("JINA_API_KEY",),
        "https://jina.ai/reader/",
    ),
)

# ----------------------------------------------------------------------- agentic
AGENTIC_CREDENTIALS: tuple[CredentialSpec, ...] = (
    CredentialSpec(
        "skyvern",
        "Skyvern",
        "Agentic",
        ("SKYVERN_API_KEY",),
        "https://github.com/Skyvern-AI/skyvern",
        optional_vars=("SKYVERN_BASE_URL",),
    ),
    CredentialSpec(
        "stagehand",
        "Stagehand",
        "Agentic",
        (),
        "https://github.com/browserbase/stagehand",
        optional_vars=("MODEL_API_KEY",),
        note="Needs a model key plus BROWSERBASE_API_KEY for hosted sessions.",
    ),
    CredentialSpec(
        "browser_use",
        "Browser Use",
        "Agentic",
        (),
        "https://github.com/browser-use/browser-use",
        note="Needs one of the AI model keys above.",
    ),
)

ALL_CREDENTIALS: tuple[CredentialSpec, ...] = (
    *AI_CREDENTIALS,
    *ENGINE_CREDENTIALS,
    *REMOTE_BROWSER_CREDENTIALS,
    *MANAGED_FETCH_CREDENTIALS,
    *DISCOVERY_CREDENTIALS,
    *SEMANTIC_CREDENTIALS,
    *AGENTIC_CREDENTIALS,
)

# ------------------------------------------------------------ behaviour settings
SETTINGS_SPECS: tuple[SettingSpec, ...] = (
    SettingSpec("SRWS_USER_AGENT", "User agent sent with every request", ""),
    SettingSpec("SRWS_REQUESTS_PER_SECOND", "Per-host request rate", "1.5"),
    SettingSpec("SRWS_CONCURRENCY_PER_HOST", "Parallel requests per host", "2"),
    SettingSpec("SRWS_MAX_RETRIES", "Retries before a request gives up", "3"),
    SettingSpec("SRWS_MAX_CRAWL_PAGES", "Default page limit for a crawl", "50"),
    SettingSpec("SRWS_HARD_MAX_PAGES", "Absolute page ceiling", "2000"),
    SettingSpec("SRWS_MAX_ROWS", "Row ceiling for one dataset", "500000"),
    SettingSpec("SRWS_MAX_PREVIEW_ROWS", "Rows rendered in the table view", "1000"),
    SettingSpec("SRWS_MAX_HTML_BYTES", "Largest HTML response read", "20971520"),
    SettingSpec("SRWS_MAX_JSON_SAMPLE_BYTES", "Largest JSON sample during discovery", "2097152"),
    SettingSpec("SRWS_MAX_DOWNLOAD_BYTES", "Largest file download", "209715200"),
    SettingSpec("SRWS_HTTP_TIMEOUT", "HTTP timeout in seconds", "30"),
    SettingSpec("SRWS_BROWSER_TIMEOUT", "Browser timeout in seconds", "45"),
    SettingSpec("SRWS_MAX_REDIRECTS", "Redirect hops allowed", "5"),
    SettingSpec("SRWS_MAX_SCROLLS", "Scroll/click cycles for infinite lists", "25"),
    SettingSpec("SRWS_RUNS_DIR", "Where run artifacts are written", "runs/"),
    SettingSpec("SRWS_CACHE_DIR", "Where caches are written", ".cache/"),
    SettingSpec(
        "SRWS_ALLOW_PRIVATE_NETWORKS",
        "DANGEROUS: lets the guard reach private addresses. Tests and the offline demo only",
        "false",
    ),
    SettingSpec("SRWS_ANTHROPIC_MODEL", "Override the Anthropic model", "claude-sonnet-5"),
    SettingSpec("SRWS_OPENAI_MODEL", "Override the OpenAI model", "gpt-4o-mini"),
    SettingSpec("SRWS_GOOGLE_MODEL", "Override the Gemini model", "gemini-3.7-flash"),
    SettingSpec("SRWS_LITELLM_MODEL", "Override the LiteLLM model string", "gpt-4o-mini"),
)


def by_id(credential_id: str) -> CredentialSpec | None:
    for spec in ALL_CREDENTIALS:
        if spec.id == credential_id:
            return spec
    return None


def env_keys_for(credential_id: str) -> tuple[str, ...]:
    spec = by_id(credential_id)
    return spec.env_vars if spec else ()


def all_env_names() -> list[str]:
    """Every variable the application reads, credentials and settings alike."""
    names: list[str] = []
    for spec in ALL_CREDENTIALS:
        names.extend(spec.env_vars)
        names.extend(spec.optional_vars)
    names.extend(spec.name for spec in SETTINGS_SPECS)
    return sorted(set(names))


def categories() -> dict[str, list[CredentialSpec]]:
    grouped: dict[str, list[CredentialSpec]] = {}
    for spec in ALL_CREDENTIALS:
        grouped.setdefault(spec.category, []).append(spec)
    return grouped


def render_env_example() -> str:
    """Generate the contents of ``.env.example`` from these declarations."""
    lines = [
        "# Smart Research Web Scraper — optional configuration.",
        "#",
        "# The application runs fully with the deterministic local core and NO keys.",
        "# Copy this file to .env and fill in only what you intend to use.",
        "#",
        "# This file is generated from src/scraper_app/credentials.py.",
        "# Run `python scripts/sync_env_example.py` after adding a provider.",
        "",
    ]
    for category, specs in categories().items():
        lines.append("# " + "=" * 68)
        lines.append(f"# {category}")
        lines.append("# " + "=" * 68)
        for spec in specs:
            if spec.note:
                lines.append(f"# {spec.label}: {spec.note}")
            elif spec.docs:
                lines.append(f"# {spec.label} — {spec.docs}")
            for var in spec.env_vars:
                lines.append(f"{var}=")
            for var in spec.optional_vars:
                lines.append(f"# {var}=        (optional)")
        lines.append("")

    lines.append("# " + "=" * 68)
    lines.append("# Application behaviour — every value has a safe default")
    lines.append("# " + "=" * 68)
    for setting in SETTINGS_SPECS:
        default = f"  (default: {setting.default})" if setting.default else ""
        lines.append(f"# {setting.description}{default}")
        lines.append(f"# {setting.name}=")
    lines.append("")
    return "\n".join(lines)
