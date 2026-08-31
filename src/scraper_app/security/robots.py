"""robots.txt inspection (spec section 38).

robots.txt is not an authorization system, but it is an access signal the
application respects by default. The status is always shown to the user; it is
never silently bypassed.
"""

from __future__ import annotations

import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from ..config import SETTINGS
from ..models import RobotsStatus

_CACHE: dict[str, tuple[float, RobotsStatus, object]] = {}
_CACHE_TTL = 900.0  # seconds


def robots_url_for(url: str) -> str:
    parts = urlsplit(url)
    return urljoin(f"{parts.scheme}://{parts.netloc}", "/robots.txt")


def _parse(text: str, robots_url: str) -> tuple[RobotsStatus, object | None]:
    sitemaps: list[str] = []
    for line in text.splitlines():
        if line.lower().startswith("sitemap:"):
            value = line.split(":", 1)[1].strip()
            if value:
                sitemaps.append(value)

    parser: object | None = None
    try:  # Prefer protego (Scrapy ecosystem) when installed.
        from protego import Protego  # type: ignore

        parser = Protego.parse(text)
    except Exception:  # pragma: no cover - fallback path
        rp = RobotFileParser()
        rp.parse(text.splitlines())
        parser = rp

    status = RobotsStatus(state="unknown", robots_url=robots_url, sitemaps=sitemaps)
    return status, parser


def fetch_robots(url: str, fetcher=None) -> tuple[RobotsStatus, object | None]:
    """Fetch and parse robots.txt for the host of ``url``.

    ``fetcher`` is an optional callable ``(url) -> (status_code, text)`` so the
    unit tests can run without network access.
    """
    robots_url = robots_url_for(url)
    now = time.time()
    cached = _CACHE.get(robots_url)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1], cached[2]

    if fetcher is None:
        from ..engines.http_client import fetch_text_simple

        fetcher = fetch_text_simple

    try:
        status_code, text = fetcher(robots_url)
    except Exception as exc:  # network failure -> unknown, never fatal
        status = RobotsStatus(
            state="unknown",
            robots_url=robots_url,
            detail=f"robots.txt unavailable ({exc.__class__.__name__})",
        )
        _CACHE[robots_url] = (now, status, None)
        return status, None

    if status_code == 404:
        status = RobotsStatus(
            state="allowed", robots_url=robots_url, detail="No robots.txt published."
        )
        _CACHE[robots_url] = (now, status, None)
        return status, None
    if status_code >= 400 or not text:
        status = RobotsStatus(
            state="unknown", robots_url=robots_url, detail=f"robots.txt returned {status_code}."
        )
        _CACHE[robots_url] = (now, status, None)
        return status, None

    status, parser = _parse(text, robots_url)
    _CACHE[robots_url] = (now, status, parser)
    return status, parser


def check(url: str, user_agent: str | None = None, fetcher=None) -> RobotsStatus:
    """Return the robots status for one URL."""
    agent = user_agent or SETTINGS.user_agent
    status, parser = fetch_robots(url, fetcher=fetcher)
    if parser is None:
        return status

    allowed = True
    crawl_delay: float | None = None
    try:
        if hasattr(parser, "can_fetch") and hasattr(parser, "crawl_delay"):
            allowed = bool(parser.can_fetch(url, agent))  # type: ignore[call-arg]
            delay = parser.crawl_delay(agent)  # type: ignore[call-arg]
            crawl_delay = float(delay) if delay else None
    except TypeError:
        # urllib RobotFileParser has the reversed signature.
        allowed = bool(parser.can_fetch(agent, url))  # type: ignore[union-attr]
        delay = parser.crawl_delay(agent)  # type: ignore[union-attr]
        crawl_delay = float(delay) if delay else None
    except Exception:
        return status.model_copy(
            update={"state": "unknown", "detail": "robots.txt could not be interpreted."}
        )

    return status.model_copy(
        update={
            "state": "allowed" if allowed else "restricted",
            "crawl_delay": crawl_delay,
            "detail": status.detail
            or ("Allowed for this path." if allowed else "Disallowed for this path."),
        }
    )


def clear_cache() -> None:
    _CACHE.clear()
