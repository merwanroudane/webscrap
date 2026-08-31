"""Automatic data dictionary (spec section 31).

Each variable is documented with its label, dtype, example, missing rate,
unique count, source and — importantly for research integrity — whether the
name came from the source itself, from a heuristic, from the user, or from AI.
"""

from __future__ import annotations

import pandas as pd

from ..models import ExtractionSchema, NameSource


def build(
    frame: pd.DataFrame,
    *,
    schema: ExtractionSchema | None = None,
    source_url: str = "",
    engine: str = "",
    labels: dict[str, str] | None = None,
    notes: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Return the data dictionary as a DataFrame ready for display and export."""
    labels = labels or {}
    notes = notes or {}
    spec_by_name = {spec.name: spec for spec in (schema.fields if schema else [])}

    rows: list[dict[str, object]] = []
    total = max(len(frame), 1)
    for column in frame.columns:
        series = frame[column]
        non_null = series.dropna()
        spec = spec_by_name.get(str(column))
        is_provenance = str(column).startswith("_")

        if is_provenance:
            name_source = NameSource.SOURCE_NATIVE.value
            note = "Provenance column added by the application."
        elif spec is not None:
            name_source = spec.name_source.value
            note = spec.notes or ""
        else:
            name_source = NameSource.SOURCE_NATIVE.value
            note = ""

        rows.append(
            {
                "variable": str(column),
                "label": labels.get(str(column)) or (spec.label if spec else None) or str(column),
                "dtype": str(series.dtype),
                "example": str(non_null.iloc[0])[:80] if not non_null.empty else "",
                "missing_pct": round(float(series.isna().sum()) / total * 100, 2),
                "unique_count": int(non_null.nunique()) if not non_null.empty else 0,
                "source": source_url,
                "extraction_method": engine,
                "name_source": name_source,
                "notes": notes.get(str(column), note),
            }
        )
    return pd.DataFrame(rows)


def to_csv_bytes(dictionary: pd.DataFrame) -> bytes:
    return dictionary.to_csv(index=False).encode("utf-8-sig")


def to_markdown(dictionary: pd.DataFrame) -> str:
    try:
        return dictionary.to_markdown(index=False)
    except Exception:
        return dictionary.to_string(index=False)
