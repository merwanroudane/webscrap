"""Pagination detection (spec section 27).

Detects: numeric page parameters, offset/limit, rel=next links, next buttons,
load-more controls and infinite scroll hints. The detector only proposes a
plan; :mod:`scraper_app.extraction.paginator` executes it with hard stop
conditions.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urljoin, urlsplit

from lxml import html as lxml_html

from ..models import Confidence, PaginationPlan, PaginationType

_PAGE_PARAMS = ("page", "p", "pagenum", "page_number", "pageindex", "pg", "start_page")
_OFFSET_PARAMS = ("offset", "start", "from", "skip")
_NEXT_TEXT = re.compile(r"(?i)^\s*(next|next page|older|more|›|»|→|التالي|التالية|المزيد)\s*$")
_LOAD_MORE_TEXT = re.compile(
    r"(?i)(load more|show more|view more|see more|عرض المزيد|تحميل المزيد)"
)
_INFINITE_HINT = re.compile(
    r"(?i)(infinite[-_ ]?scroll|data-infinite|IntersectionObserver|scroll-?loader|lazy-?load-?more)"
)


def _template_from_query(url: str, param: str) -> str:
    parts = urlsplit(url)
    pairs = [(k, v) for k, v in parse_qsl(parts.query) if k.lower() != param.lower()]
    pairs.append((param, "{page}"))
    query = "&".join(f"{k}={v}" for k, v in pairs)
    return f"{parts.scheme}://{parts.netloc}{parts.path}?{query}"


def detect_from_url(url: str) -> PaginationPlan | None:
    """A page/offset parameter already present in the URL is the strongest signal."""
    query = dict(parse_qsl(urlsplit(url).query))
    for key, value in query.items():
        lowered = key.lower()
        if lowered in _PAGE_PARAMS and value.isdigit():
            return PaginationPlan(
                type=PaginationType.PAGE_NUMBER,
                param=key,
                start=int(value),
                url_template=_template_from_query(url, key),
                detected_from="url_query",
                confidence=Confidence.HIGH,
            )
        if lowered in _OFFSET_PARAMS and value.isdigit():
            return PaginationPlan(
                type=PaginationType.OFFSET_LIMIT,
                param=key,
                start=int(value),
                step=int(query.get("limit", query.get("per_page", "50")) or 50),
                url_template=_template_from_query(url, key),
                detected_from="url_query",
                confidence=Confidence.HIGH,
            )
    return None


def detect_from_html(html: str, base_url: str) -> PaginationPlan | None:
    """Look for rel=next, next links/buttons, load-more and infinite scroll."""
    try:
        tree = lxml_html.fromstring(html)
    except Exception:
        return None

    for node in tree.xpath("//link[@rel='next']|//a[@rel='next']"):
        href = node.get("href")
        if href:
            return PaginationPlan(
                type=PaginationType.NEXT_LINK,
                next_selector="[rel=next]",
                url_template=urljoin(base_url, href),
                detected_from="rel_next",
                confidence=Confidence.HIGH,
            )

    numbered: list[tuple[int, str]] = []
    for anchor in tree.xpath("//a[@href]"):
        text = (anchor.text_content() or "").strip()
        href = anchor.get("href") or ""
        if _NEXT_TEXT.match(text) or "next" in (anchor.get("class") or "").lower():
            absolute = urljoin(base_url, href)
            query = dict(parse_qsl(urlsplit(absolute).query))
            for key, value in query.items():
                if key.lower() in _PAGE_PARAMS and value.isdigit():
                    return PaginationPlan(
                        type=PaginationType.PAGE_NUMBER,
                        param=key,
                        start=1,
                        url_template=_template_from_query(absolute, key),
                        detected_from="next_link_query",
                        confidence=Confidence.HIGH,
                    )
            return PaginationPlan(
                type=PaginationType.NEXT_LINK,
                next_selector="a[rel=next], a.next",
                url_template=absolute,
                detected_from="next_link_text",
                confidence=Confidence.MEDIUM,
            )
        if text.isdigit() and 1 <= len(text) <= 4:
            numbered.append((int(text), urljoin(base_url, href)))

    if len(numbered) >= 2:
        numbered.sort()
        _, sample = numbered[-1]
        query = dict(parse_qsl(urlsplit(sample).query))
        for key, value in query.items():
            if key.lower() in _PAGE_PARAMS and value.isdigit():
                return PaginationPlan(
                    type=PaginationType.PAGE_NUMBER,
                    param=key,
                    start=1,
                    url_template=_template_from_query(sample, key),
                    detected_from="numbered_links",
                    confidence=Confidence.MEDIUM,
                )
        # Path-style pagination, e.g. /news/page/3
        path_match = re.search(r"/(page|p)/(\d+)/?$", urlsplit(sample).path)
        if path_match:
            template = re.sub(r"/(page|p)/\d+/?$", f"/{path_match.group(1)}/{{page}}", sample)
            return PaginationPlan(
                type=PaginationType.PAGE_NUMBER,
                param="page",
                start=1,
                url_template=template,
                detected_from="numbered_path",
                confidence=Confidence.MEDIUM,
            )

    for button in tree.xpath("//button|//a"):
        text = (button.text_content() or "").strip()
        if _LOAD_MORE_TEXT.search(text):
            classes = (button.get("class") or "").split()
            selector = f"{button.tag}.{classes[0]}" if classes else button.tag
            return PaginationPlan(
                type=PaginationType.LOAD_MORE,
                next_selector=selector,
                detected_from="load_more_button",
                confidence=Confidence.MEDIUM,
            )

    if _INFINITE_HINT.search(html or ""):
        return PaginationPlan(
            type=PaginationType.INFINITE_SCROLL,
            detected_from="infinite_scroll_hint",
            confidence=Confidence.LOW,
        )
    return None


def detect(url: str, html: str | None = None) -> PaginationPlan:
    """Combine URL and HTML evidence into a single plan."""
    plan = detect_from_url(url)
    if plan:
        return plan
    if html:
        plan = detect_from_html(html, url)
        if plan:
            return plan
    return PaginationPlan(type=PaginationType.NONE, confidence=Confidence.LOW)


def detect_for_api(url: str, payload: object) -> PaginationPlan:
    """Pagination plan for a JSON endpoint (page param, offset or cursor)."""
    from .api_detector import detect_cursor_field

    plan = detect_from_url(url)
    if plan:
        return plan
    cursor = detect_cursor_field(payload)
    if cursor:
        return PaginationPlan(
            type=PaginationType.CURSOR,
            cursor_path=cursor,
            detected_from="api_cursor_field",
            confidence=Confidence.MEDIUM,
        )
    parts = urlsplit(url)
    if not parts.query:
        return PaginationPlan(type=PaginationType.NONE, confidence=Confidence.LOW)
    return PaginationPlan(type=PaginationType.NONE, confidence=Confidence.LOW)
