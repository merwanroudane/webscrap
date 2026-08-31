"""Playwright network observation (spec section 22).

Loads a page in Chromium, listens to XHR/fetch responses, ignores static
assets, and reports JSON responses that look like datasets. When a stable
endpoint is found the router prefers calling it directly with HTTPX — faster,
cheaper and reproducible.

Never stores request headers: only the URL, method, content type and a bounded
sample of the response shape.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from ..config import SETTINGS
from ..logging_config import RunLogger
from ..security.url_guard import guard_url, is_allowed
from . import api_detector

_IGNORED_RESOURCE_TYPES = {"image", "media", "font", "stylesheet", "manifest", "other"}
_IGNORED_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".css", ".woff",
    ".woff2", ".ttf", ".mp4", ".webm", ".map",
)


@lru_cache(maxsize=1)
def playwright_available() -> tuple[bool, str]:
    """Report whether Playwright and a Chromium build are usable."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception:
        return False, (
            "Browser mode needs the optional Playwright package "
            "(pip install playwright && playwright install chromium)."
        )
    try:
        import os

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            path = p.chromium.executable_path
        if path and os.path.exists(path):
            return True, ""
        return False, "Chromium is not installed (run: playwright install chromium)."
    except Exception as exc:
        return False, f"Browser mode is unavailable: {exc.__class__.__name__}."


def probe_with_browser(
    url: str,
    *,
    wait_for: str | None = None,
    timeout: float | None = None,
    logger: RunLogger | None = None,
    scrolls: int = 0,
) -> dict[str, Any]:
    """Render a page and capture dataset-like JSON responses.

    Returns ``{available, html, api_candidates, requests_seen, reason}``.
    """
    ok, reason = playwright_available()
    if not ok:
        return {"available": False, "reason": reason, "api_candidates": [], "html": ""}

    guarded = guard_url(url)
    timeout_ms = int((timeout or SETTINGS.limits.browser_timeout) * 1000)

    from playwright.sync_api import sync_playwright

    captured: list[dict[str, Any]] = []
    seen = 0

    def handle_response(response) -> None:  # pragma: no cover - requires browser
        nonlocal seen
        try:
            request = response.request
            if request.resource_type in _IGNORED_RESOURCE_TYPES:
                return
            target = response.url
            if target.lower().split("?")[0].endswith(_IGNORED_EXTENSIONS):
                return
            seen += 1
            content_type = (response.headers.get("content-type") or "").lower()
            if "json" not in content_type:
                return
            if not is_allowed(target):
                return
            body = response.text()
            if len(body) > SETTINGS.limits.max_json_sample_bytes:
                body = body[: SETTINGS.limits.max_json_sample_bytes]
            captured.append(
                {
                    "url": target,
                    "method": request.method,
                    "content_type": content_type.split(";")[0],
                    "status": response.status,
                    "body": body,
                }
            )
        except Exception:
            return

    html = ""
    try:  # pragma: no cover - requires a real browser
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=SETTINGS.user_agent)
            page = context.new_page()
            page.on("response", handle_response)
            page.goto(guarded.url, timeout=timeout_ms, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 15000))
            except Exception:
                pass
            if wait_for:
                try:
                    page.wait_for_selector(wait_for, timeout=min(timeout_ms, 15000))
                except Exception:
                    pass
            for _ in range(max(0, scrolls)):
                page.mouse.wheel(0, 20000)
                page.wait_for_timeout(800)
            html = page.content()
            context.close()
            browser.close()
    except Exception as exc:
        return {
            "available": False,
            "reason": f"The browser could not load this page ({exc.__class__.__name__}).",
            "api_candidates": [],
            "html": "",
        }

    candidates = []
    for item in captured:
        candidate = api_detector.candidate_from_response(
            item["url"],
            item["body"],
            content_type=item["content_type"],
            status=item["status"],
            originating_page=guarded.url,
            discovered_by="network",
            method=item["method"],
        )
        if candidate and (candidate.record_count or len(candidate.sample_keys) >= 2):
            candidate.score = min(0.97, candidate.score + 0.1)  # observed, not guessed
            candidates.append(candidate)

    candidates.sort(key=lambda c: (c.record_count or 0, c.score), reverse=True)
    if logger:
        logger.log(
            "network_probe",
            "browser_probe_complete",
            url=guarded.url,
            engine="playwright",
            responses_seen=seen,
            json_candidates=len(candidates),
        )
    return {
        "available": True,
        "reason": "",
        "html": html,
        "api_candidates": candidates[:8],
        "requests_seen": seen,
    }
