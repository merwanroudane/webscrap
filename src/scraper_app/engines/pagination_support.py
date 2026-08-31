"""HTML pagination walker shared by the HTML-based engines (spec section 27).

Implements URL-template, rel=next and next-link pagination with the full set of
stop conditions: max pages, absent next link, repeated page hash, guard
failures and per-page errors.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from urllib.parse import urljoin

from lxml import html as lxml_html

from ..config import SETTINGS
from ..exceptions import ScraperError
from ..logging_config import RunLogger
from ..models import ExtractionRequest, PaginationType
from ..security.url_guard import is_allowed


@dataclass
class Page:
    number: int
    url: str
    html: str
    error: ScraperError | None = None


def _next_link(html: str, base_url: str, selector: str | None) -> str | None:
    try:
        tree = lxml_html.fromstring(html)
    except Exception:
        return None
    nodes = tree.xpath("//link[@rel='next']|//a[@rel='next']")
    if not nodes and selector:
        try:
            nodes = tree.cssselect(selector)
        except Exception:
            nodes = []
    if not nodes:
        nodes = [
            a
            for a in tree.xpath("//a[@href]")
            if (a.text_content() or "").strip().lower() in {"next", "next page", "›", "»", "التالي"}
            or "next" in (a.get("class") or "").lower()
        ]
    for node in nodes:
        href = node.get("href")
        if href:
            candidate = urljoin(base_url, href)
            if is_allowed(candidate):
                return candidate
    return None


def iter_pages(
    request: ExtractionRequest,
    *,
    fetcher: Callable[[str], object],
    limit_pages: int | None = None,
    progress: Callable[[int, int, str], None] | None = None,
    logger: RunLogger | None = None,
) -> Iterator[Page]:
    """Yield each page of HTML according to the request's pagination plan."""
    plan = request.pagination
    max_pages = min(
        limit_pages or request.max_pages or 1,
        SETTINGS.limits.hard_max_pages,
    )
    if plan.type == PaginationType.NONE:
        max_pages = min(max_pages, 1)

    current_url = request.url
    seen_hashes: set[str] = set()

    for index in range(max_pages):
        page_number = plan.start + index * max(plan.step, 1)
        if (
            plan.type in {PaginationType.PAGE_NUMBER, PaginationType.OFFSET_LIMIT}
            and plan.url_template
        ):
            value = (
                page_number
                if plan.type == PaginationType.PAGE_NUMBER
                else (page_number - plan.start) * max(plan.step, 1)
            )
            current_url = plan.url_template.replace("{page}", str(value))

        if progress:
            progress(index + 1, max_pages, current_url)

        try:
            response = fetcher(current_url)
            html = response.text  # type: ignore[attr-defined]
            url = response.url  # type: ignore[attr-defined]
        except ScraperError as exc:
            yield Page(number=index + 1, url=current_url, html="", error=exc)
            return

        digest = hashlib.sha256(html.encode("utf-8", errors="ignore")).hexdigest()
        if digest in seen_hashes:
            if logger:
                logger.warn("pagination", "repeated_page_hash", url=url, page=index + 1)
            return
        seen_hashes.add(digest)

        yield Page(number=index + 1, url=url, html=html)

        if plan.type in {
            PaginationType.NONE,
            PaginationType.LOAD_MORE,
            PaginationType.INFINITE_SCROLL,
        }:
            return
        if plan.type in {PaginationType.NEXT_LINK, PaginationType.NEXT_BUTTON}:
            nxt = _next_link(html, url, plan.next_selector)
            if not nxt or nxt == current_url:
                return
            current_url = nxt
