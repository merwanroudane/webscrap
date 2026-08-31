"""sitemap.xml and feed discovery (spec sections 4M / 28).

Sitemaps make multi-page crawling cheap and polite: the site itself publishes
the URL list, so no link-graph spidering is needed.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from lxml import etree

from ..security.url_guard import is_allowed

_SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def sitemap_urls_for(url: str, robots_sitemaps: list[str] | None = None) -> list[str]:
    """Candidate sitemap locations: robots.txt entries first, then conventions."""
    parts = urlsplit(url)
    root = f"{parts.scheme}://{parts.netloc}"
    candidates = list(robots_sitemaps or [])
    for path in ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml"):
        candidate = urljoin(root, path)
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def parse_sitemap(content: bytes | str) -> tuple[list[str], list[str]]:
    """Return ``(page_urls, nested_sitemap_urls)``."""
    if isinstance(content, str):
        content = content.encode("utf-8", errors="replace")
    try:
        root = etree.fromstring(
            content, parser=etree.XMLParser(resolve_entities=False, recover=True)
        )
    except Exception:
        return [], []
    if root is None:
        return [], []

    tag = etree.QName(root).localname.lower() if root.tag else ""
    locs = [
        (node.text or "").strip()
        for node in root.iter()
        if node.tag and etree.QName(node).localname.lower() == "loc" and node.text
    ]
    locs = [loc for loc in locs if loc.startswith(("http://", "https://"))]
    if tag == "sitemapindex":
        return [], locs
    return locs, []


def fetch_sitemap_urls(
    url: str,
    robots_sitemaps: list[str] | None = None,
    fetcher=None,
    max_urls: int = 1000,
    max_sitemaps: int = 5,
) -> list[str]:
    """Collect page URLs from a site's sitemap(s), bounded and guarded."""
    if fetcher is None:
        from ..engines.http_client import fetch as fetcher  # type: ignore

    queue = sitemap_urls_for(url, robots_sitemaps)
    seen: set[str] = set()
    collected: list[str] = []
    processed = 0

    while queue and processed < max_sitemaps and len(collected) < max_urls:
        candidate = queue.pop(0)
        if candidate in seen or not is_allowed(candidate):
            continue
        seen.add(candidate)
        processed += 1
        try:
            response = fetcher(candidate, max_bytes=5 * 1024 * 1024, max_retries=0)
        except Exception:
            continue
        if response.status_code >= 400:
            continue
        pages, nested = parse_sitemap(response.content)
        collected.extend(pages)
        queue.extend(nested[: max_sitemaps - processed])

    unique: list[str] = []
    seen_pages: set[str] = set()
    for page in collected:
        if page not in seen_pages:
            seen_pages.add(page)
            unique.append(page)
        if len(unique) >= max_urls:
            break
    return unique


_FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/feed+json")


def discover_feeds(html: str, base_url: str) -> list[str]:
    """Find RSS/Atom feed links declared in the page head."""
    feeds: list[str] = []
    for match in re.finditer(r"<link[^>]+>", html or "", flags=re.IGNORECASE):
        tag = match.group(0)
        if not any(feed_type in tag.lower() for feed_type in _FEED_TYPES):
            continue
        href = re.search(r"""href\s*=\s*["']([^"']+)["']""", tag, flags=re.IGNORECASE)
        if href:
            absolute = urljoin(base_url, href.group(1))
            if absolute not in feeds and is_allowed(absolute):
                feeds.append(absolute)
    return feeds[:10]


def parse_feed(content: bytes | str) -> list[dict[str, str]]:
    """Parse an RSS/Atom feed into flat records using feedparser."""
    try:
        import feedparser  # type: ignore
    except Exception:
        return []
    parsed = feedparser.parse(content)
    rows: list[dict[str, str]] = []
    for entry in parsed.entries:
        rows.append(
            {
                "title": str(entry.get("title", "")),
                "link": str(entry.get("link", "")),
                "published": str(entry.get("published", entry.get("updated", ""))),
                "author": str(entry.get("author", "")),
                "summary": re.sub(r"<[^>]+>", " ", str(entry.get("summary", "")))[:1000].strip(),
                "id": str(entry.get("id", "")),
            }
        )
    return rows
