"""Direct-data-file detection (spec section 4A / Tier 0).

Downloading a published CSV/XLSX/JSON/Parquet beats scraping it out of HTML,
so this runs before anything else.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

DATA_EXTENSIONS = {
    ".csv": "csv",
    ".tsv": "tsv",
    ".txt": "text",
    ".json": "json",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".xml": "xml",
    ".xls": "excel",
    ".xlsx": "excel",
    ".xlsm": "excel",
    ".parquet": "parquet",
    ".feather": "feather",
    ".zip": "zip",
    ".dta": "stata",
    ".sav": "spss",
    ".rds": "rds",
}

DOCUMENT_EXTENSIONS = {
    ".pdf": "pdf",
    ".doc": "word",
    ".docx": "word",
    ".ppt": "powerpoint",
    ".pptx": "powerpoint",
}

CONTENT_TYPE_FORMATS = {
    "text/csv": "csv",
    "application/csv": "csv",
    "text/tab-separated-values": "tsv",
    "application/json": "json",
    "application/x-ndjson": "jsonl",
    "application/ld+json": "json",
    "application/vnd.ms-excel": "excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "excel",
    "application/vnd.apache.parquet": "parquet",
    "application/zip": "zip",
    "application/pdf": "pdf",
    "application/xml": "xml",
    "text/xml": "xml",
    "application/rss+xml": "feed",
    "application/atom+xml": "feed",
}

_FEED_HINT = re.compile(r"(?i)(/feed/?$|/rss|\.rss$|atom\.xml|feed\.xml)")


def format_from_url(url: str) -> str | None:
    """Return a data/document format inferred from the URL path."""
    path = urlsplit(url).path.lower()
    for ext, fmt in {**DATA_EXTENSIONS, **DOCUMENT_EXTENSIONS}.items():
        if path.endswith(ext):
            return fmt
    if _FEED_HINT.search(url):
        return "feed"
    return None


def format_from_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    return CONTENT_TYPE_FORMATS.get(content_type.split(";")[0].strip().lower())


def detect_format(url: str, content_type: str | None = None) -> str | None:
    """Content-Type wins over the URL extension when both are present."""
    return format_from_content_type(content_type) or format_from_url(url)


def is_tabular_format(fmt: str | None) -> bool:
    return fmt in {"csv", "tsv", "json", "jsonl", "excel", "parquet", "feather", "stata", "spss", "rds"}


def is_document_format(fmt: str | None) -> bool:
    return fmt in {"pdf", "word", "powerpoint"}


def collect_file_links(links: list[tuple[str, str]]) -> list[dict[str, str]]:
    """Turn ``(href, text)`` pairs into downloadable-file descriptors."""
    files: list[dict[str, str]] = []
    seen: set[str] = set()
    for href, text in links:
        fmt = format_from_url(href)
        if not fmt or fmt == "feed" or href in seen:
            continue
        seen.add(href)
        files.append(
            {
                "url": href,
                "format": fmt,
                "label": (text or "").strip()[:120] or urlsplit(href).path.rsplit("/", 1)[-1],
                "kind": "document" if is_document_format(fmt) else "data",
            }
        )
    return files
