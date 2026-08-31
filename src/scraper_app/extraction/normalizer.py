"""Column naming and record normalization used before cleaning.

Only structural normalization happens here (stable column order, provenance
columns, safe names). Value-level cleaning is a separate, reversible step in
:mod:`scraper_app.data.cleaner`.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import pandas as pd

PROVENANCE_COLUMNS = ["_source_url", "_source_page", "_retrieved_at", "_extraction_method"]

_INVALID = re.compile(r"[^0-9a-zA-Z_؀-ۿ]+")


def safe_column_name(name: str, index: int = 0) -> str:
    """Return a safe name, preserving the leading underscore of provenance columns."""
    raw = str(name).strip()
    provenance = raw.startswith("_")
    cleaned = _INVALID.sub("_", raw).strip("_")
    cleaned = re.sub(r"_+", "_", cleaned)
    if not cleaned:
        cleaned = f"column_{index}"
    if cleaned[0].isdigit():
        cleaned = f"c_{cleaned}"
    return ("_" + cleaned if provenance else cleaned)[:64]


def standardize_columns(frame: pd.DataFrame, lower: bool = True) -> tuple[pd.DataFrame, dict[str, str]]:
    """Return a frame with safe, unique column names plus the rename map."""
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for index, column in enumerate(frame.columns):
        new = safe_column_name(column, index)
        if lower:
            new = new.lower()
        base = new
        suffix = 2
        while new in used:
            new = f"{base}_{suffix}"
            suffix += 1
        used.add(new)
        mapping[str(column)] = new
    return frame.rename(columns=mapping), mapping


def add_provenance_columns(
    frame: pd.DataFrame, *, source_url: str, method: str, retrieved_at: datetime | None = None
) -> pd.DataFrame:
    """Add row-level provenance columns without overwriting engine-supplied ones."""
    result = frame.copy()
    stamp = (retrieved_at or datetime.now(UTC)).isoformat()
    if "_source_url" not in result.columns:
        result["_source_url"] = source_url
    if "_retrieved_at" not in result.columns:
        result["_retrieved_at"] = stamp
    if "_extraction_method" not in result.columns:
        result["_extraction_method"] = method
    return result


def hide_provenance_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the dataset without provenance columns (they stay in the manifest)."""
    return frame[[c for c in frame.columns if not str(c).startswith("_")]]


def records_to_frame(records: list[dict[str, Any]], columns: list[str] | None = None) -> pd.DataFrame:
    """Stable-order DataFrame construction shared by engines and the run store."""
    if not records:
        return pd.DataFrame(columns=columns or [])
    ordered: list[str] = list(columns or [])
    for record in records:
        for key in record:
            if key not in ordered:
                ordered.append(key)
    # Provenance columns always sit at the end.
    ordered = [c for c in ordered if not str(c).startswith("_")] + [
        c for c in ordered if str(c).startswith("_")
    ]
    return pd.DataFrame([{key: record.get(key) for key in ordered} for record in records])
