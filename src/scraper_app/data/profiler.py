"""Data quality report (spec section 32).

Profiling is sampled above a threshold so a very large dataset never blocks the
UI. The report is deliberately factual: it counts and describes, it does not
modify the data.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..models import QualityReport

SAMPLE_THRESHOLD = 200_000
HIGH_CARDINALITY_RATIO = 0.9


def profile(
    frame: pd.DataFrame,
    *,
    conversion_failures: dict[str, int] | None = None,
    schema_drift: list[str] | None = None,
    duplicate_subset: list[str] | None = None,
) -> QualityReport:
    """Compute the metrics shown in the Quality tab."""
    if frame is None or frame.empty:
        return QualityReport(rows=0, columns=0)

    sampled = len(frame) > SAMPLE_THRESHOLD
    working = frame.sample(SAMPLE_THRESHOLD, random_state=0) if sampled else frame

    data_columns = [c for c in frame.columns if not str(c).startswith("_")]
    subset = duplicate_subset or data_columns or None

    missing_cells = int(working.isna().to_numpy().sum())
    total_cells = int(working.shape[0] * working.shape[1]) or 1

    stats: list[dict[str, Any]] = []
    constant: list[str] = []
    high_cardinality: list[str] = []

    for column in frame.columns:
        series = working[column]
        non_null = series.dropna()
        unique = int(non_null.nunique()) if not non_null.empty else 0
        entry: dict[str, Any] = {
            "column": str(column),
            "dtype": str(series.dtype),
            "missing": int(series.isna().sum()),
            "missing_pct": round(float(series.isna().mean() * 100), 2),
            "unique": unique,
            "example": str(non_null.iloc[0])[:60] if not non_null.empty else "",
        }
        if pd.api.types.is_numeric_dtype(series) and not non_null.empty:
            entry["min"] = float(np.nanmin(non_null.astype(float)))
            entry["max"] = float(np.nanmax(non_null.astype(float)))
            entry["mean"] = round(float(np.nanmean(non_null.astype(float))), 4)
        elif pd.api.types.is_datetime64_any_dtype(series) and not non_null.empty:
            entry["min"] = str(non_null.min())
            entry["max"] = str(non_null.max())

        if unique == 1 and not str(column).startswith("_"):
            constant.append(str(column))
        if (
            not non_null.empty
            and unique / max(len(non_null), 1) > HIGH_CARDINALITY_RATIO
            and unique > 20
        ):
            high_cardinality.append(str(column))
        stats.append(entry)

    duplicates = int(working.duplicated(subset=subset).sum()) if subset else 0

    warnings: list[str] = []
    if constant:
        warnings.append(f"Constant columns (one value only): {', '.join(constant[:6])}")
    if duplicates:
        warnings.append(f"{duplicates:,} duplicate rows detected (not removed automatically).")
    if conversion_failures:
        total_failures = sum(conversion_failures.values())
        warnings.append(
            f"{total_failures:,} values could not be converted and were left unchanged: "
            + ", ".join(f"{k} ({v})" for k, v in list(conversion_failures.items())[:5])
        )
    if sampled:
        warnings.append(
            f"Quality metrics were computed on a random sample of {SAMPLE_THRESHOLD:,} rows."
        )

    return QualityReport(
        rows=int(len(frame)),
        columns=int(frame.shape[1]),
        missing_cells=missing_cells,
        missing_pct=round(missing_cells / total_cells * 100, 2),
        duplicate_rows=duplicates,
        constant_columns=constant,
        high_cardinality_columns=high_cardinality,
        conversion_failures=dict(conversion_failures or {}),
        column_stats=stats,
        schema_drift=list(schema_drift or []),
        warnings=warnings,
        sampled=sampled,
    )


def missingness_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Per-column missing percentage, ready for the missingness chart."""
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["column", "missing_pct"])
    data = [
        {"column": str(column), "missing_pct": round(float(frame[column].isna().mean() * 100), 2)}
        for column in frame.columns
    ]
    return pd.DataFrame(data).sort_values("missing_pct", ascending=False).reset_index(drop=True)
