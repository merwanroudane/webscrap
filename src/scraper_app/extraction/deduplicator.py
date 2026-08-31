"""Deduplication levels (spec section 64).

URL, page-content hash, exact row and user-chosen key. Fuzzy matching is
deliberately *not* the default: merging near-identical observations would
destroy legitimate research data.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd

_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "ref_src")


def canonicalize_url(url: str, drop_tracking: bool = True) -> str:
    """Normalize a URL for deduplication (spec section 28)."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    if netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    query = parts.query
    if drop_tracking and query:
        pairs = [
            (key, value)
            for key, value in parse_qsl(query, keep_blank_values=True)
            if not key.lower().startswith(_TRACKING_PREFIXES)
        ]
        query = urlencode(pairs)
    return urlunsplit((scheme, netloc, path, query, ""))


def content_hash(content: str | bytes) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8", errors="ignore")
    return hashlib.sha256(content).hexdigest()


@dataclass
class DedupeReport:
    removed_rows: int = 0
    duplicate_keys: int = 0
    method: str = "none"


def drop_duplicate_rows(
    frame: pd.DataFrame, subset: list[str] | None = None, ignore_provenance: bool = True
) -> tuple[pd.DataFrame, DedupeReport]:
    """Remove exact or key-based duplicate rows and report what was removed."""
    if frame.empty:
        return frame, DedupeReport()

    columns = subset
    if columns is None and ignore_provenance:
        columns = [c for c in frame.columns if not str(c).startswith("_")] or None

    before = len(frame)
    deduped = frame.drop_duplicates(subset=columns, keep="first")
    return deduped.reset_index(drop=True), DedupeReport(
        removed_rows=before - len(deduped),
        method="key" if subset else "exact",
    )


def count_duplicates(frame: pd.DataFrame, subset: list[str] | None = None) -> int:
    if frame.empty:
        return 0
    columns = subset or [c for c in frame.columns if not str(c).startswith("_")] or None
    return int(frame.duplicated(subset=columns).sum())
