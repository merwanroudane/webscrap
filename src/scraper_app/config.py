"""Central configuration for Smart Research Web Scraper.

Every tunable limit lives here so the rest of the code contains no magic
constants. Values may be overridden through environment variables (see
``.env.example``) but always have safe, conservative defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=False)

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent.parent
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"
RUNS_DIR = Path(os.getenv("SRWS_RUNS_DIR", PROJECT_ROOT / "runs"))
CACHE_DIR = Path(os.getenv("SRWS_CACHE_DIR", PROJECT_ROOT / ".cache"))

APP_NAME = "Smart Research Web Scraper"
APP_VERSION = "0.1.0"
APP_AUTHOR = "Dr Merwan Roudane"
APP_AUTHOR_EMAIL = "merwanroudane920@gmail.com"
APP_AUTHOR_URL = "https://github.com/merwanroudane"


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "")
    try:
        return int(raw) if raw.strip() else default
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "")
    try:
        return float(raw) if raw.strip() else default
    except ValueError:
        return default


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Limits:
    """Performance and safety budgets (spec section 70)."""

    max_html_bytes: int = _int_env("SRWS_MAX_HTML_BYTES", 20 * 1024 * 1024)
    max_json_sample_bytes: int = _int_env("SRWS_MAX_JSON_SAMPLE_BYTES", 2 * 1024 * 1024)
    max_download_bytes: int = _int_env("SRWS_MAX_DOWNLOAD_BYTES", 200 * 1024 * 1024)
    max_preview_rows: int = _int_env("SRWS_MAX_PREVIEW_ROWS", 1000)
    default_max_pages: int = _int_env("SRWS_MAX_CRAWL_PAGES", 50)
    hard_max_pages: int = _int_env("SRWS_HARD_MAX_PAGES", 2000)
    max_rows: int = _int_env("SRWS_MAX_ROWS", 500_000)
    max_redirects: int = _int_env("SRWS_MAX_REDIRECTS", 5)
    http_timeout: float = _float_env("SRWS_HTTP_TIMEOUT", 30.0)
    browser_timeout: float = _float_env("SRWS_BROWSER_TIMEOUT", 45.0)
    max_scrolls: int = _int_env("SRWS_MAX_SCROLLS", 25)
    max_internal_links: int = _int_env("SRWS_MAX_INTERNAL_LINKS", 2000)
    max_repeated_candidates: int = _int_env("SRWS_MAX_REPEATED_CANDIDATES", 6)
    min_repeated_items: int = _int_env("SRWS_MIN_REPEATED_ITEMS", 4)


@dataclass(frozen=True)
class Politeness:
    """Rate limiting defaults (spec section 39)."""

    requests_per_second: float = _float_env("SRWS_REQUESTS_PER_SECOND", 1.5)
    concurrency_per_host: int = _int_env("SRWS_CONCURRENCY_PER_HOST", 2)
    jitter_seconds: float = _float_env("SRWS_JITTER_SECONDS", 0.25)
    max_retries: int = _int_env("SRWS_MAX_RETRIES", 3)
    backoff_factor: float = _float_env("SRWS_BACKOFF_FACTOR", 1.7)
    respect_retry_after: bool = True


@dataclass(frozen=True)
class SecurityPolicy:
    """URL guard policy (spec section 37)."""

    allowed_schemes: tuple[str, ...] = ("http", "https")
    allow_private_networks: bool = _bool_env("SRWS_ALLOW_PRIVATE_NETWORKS", False)
    allow_userinfo: bool = False
    blocked_ports: frozenset[int] = frozenset({22, 23, 25, 445, 3306, 5432, 6379, 9200, 11211})
    #: Exact ``host:port`` entries exempt from the non-public-address rule.
    #: Used only by the bundled offline demo; every other guard stays in force.
    allow_hosts: frozenset[str] = frozenset()
    metadata_hosts: frozenset[str] = frozenset(
        {
            "169.254.169.254",
            "metadata.google.internal",
            "metadata.goog",
            "instance-data",
        }
    )


@dataclass(frozen=True)
class Settings:
    user_agent: str = os.getenv(
        "SRWS_USER_AGENT",
        f"SmartResearchWebScraper/{APP_VERSION} (+research data collection; contact site owner if problematic)",
    )
    respect_robots_default: bool = True
    limits: Limits = field(default_factory=Limits)
    politeness: Politeness = field(default_factory=Politeness)
    security: SecurityPolicy = field(default_factory=SecurityPolicy)

    @property
    def default_headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en,ar;q=0.8",
        }


SETTINGS = Settings()

# Palette (spec sections 17 / 107.3) — used for Plotly figures so charts match the theme.
PALETTE = {
    "background": "#FBFCFE",
    "sidebar": "#F7FAFF",
    "panel": "#F1F7FF",
    "primary": "#4F86F7",
    "primary_hover": "#3F73D9",
    "mint": "#57C7A5",
    "coral": "#FF8A65",
    "gold": "#F2B84B",
    "text": "#25324A",
    "muted": "#667085",
    "border": "#D9E2F1",
    "table_header": "#EDF4FF",
    "success": "#EAF8F2",
    "warning": "#FFF6E3",
    "error": "#FFF0EE",
}

CHART_SEQUENCE = [
    PALETTE["primary"],
    PALETTE["mint"],
    PALETTE["coral"],
    PALETTE["gold"],
    "#8E7CF0",
    "#4BB3D4",
    "#E4739B",
    "#7FA6E8",
]

# Provider environment variables consulted by the capability registry.
PROVIDER_ENV_KEYS = {
    "firecrawl": ["FIRECRAWL_API_KEY"],
    "scrapegraph": ["SGAI_API_KEY"],
    "agentql": ["AGENTQL_API_KEY"],
    "browserbase": ["BROWSERBASE_API_KEY", "BROWSERBASE_PROJECT_ID"],
    "browser_use": ["BROWSER_USE_API_KEY"],
    "skyvern": ["SKYVERN_API_KEY"],
    "apify": ["APIFY_API_TOKEN"],
    "zyte": ["ZYTE_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
    "google": ["GOOGLE_API_KEY"],
}


def has_credentials(provider: str) -> bool:
    """True when every environment variable a provider needs is present."""
    keys = PROVIDER_ENV_KEYS.get(provider, [])
    return bool(keys) and all(os.getenv(k, "").strip() for k in keys)


def allow_host(hostport: str) -> None:
    """Exempt one exact ``host:port`` from the non-public-address rule.

    This exists for the bundled offline demo, which serves fixtures from
    127.0.0.1. It is deliberately narrow: the scheme, userinfo, port and
    metadata checks all still apply, and no other private address is reachable.
    A public deployment therefore stays protected even while the demo runs.
    """
    policy = SETTINGS.security
    if hostport in policy.allow_hosts:
        return
    object.__setattr__(
        SETTINGS,
        "security",
        replace(policy, allow_hosts=frozenset({*policy.allow_hosts, hostport})),
    )


def ensure_dirs() -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
