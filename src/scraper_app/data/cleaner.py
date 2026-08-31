"""Reversible cleaning pipeline (spec section 29).

Rules that are not negotiable:

* ``raw_df`` is never modified — cleaning always produces a new frame;
* every operation is opt-in and reported;
* failed numeric/date conversions are counted and surfaced, never silently
  turned into missing values;
* outliers are flagged, never deleted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

MISSING_TOKENS = {
    "", "-", "--", "n/a", "N/A", "na", "NA", "NaN", "nan", "null", "NULL", "none", "None",
    "..", "...", ":", "—", "–", "?", "غير متاح", "لا يوجد",
}

_PERCENT = re.compile(r"^\s*([-+]?[\d\s.,]+)\s*%\s*$")
_CURRENCY = re.compile(r"^\s*([$€£¥₹]|USD|EUR|GBP|SAR|AED|DZD)?\s*([-+]?[\d\s.,]+)\s*([$€£¥₹]|USD|EUR|GBP|SAR|AED|DZD)?\s*$", re.IGNORECASE)
_PARENS_NEGATIVE = re.compile(r"^\s*\(([\d\s.,]+)\)\s*$")
_NUMBER_LIKE = re.compile(r"^[-+]?[\d\s.,]+$")
_BOOL_TRUE = {"true", "yes", "y", "1", "نعم", "صحيح"}
_BOOL_FALSE = {"false", "no", "n", "0", "لا", "خطأ"}


@dataclass
class CleaningOperation:
    name: str
    columns: list[str] = field(default_factory=list)
    changed_cells: int = 0
    failures: int = 0
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation": self.name,
            "columns": ", ".join(self.columns[:12]),
            "changed_cells": self.changed_cells,
            "conversion_failures": self.failures,
            "detail": self.detail,
        }


@dataclass
class CleaningOptions:
    trim_whitespace: bool = True
    normalize_missing: bool = True
    numeric_conversion: bool = False
    parse_percentages: bool = False
    parse_currency: bool = False
    parse_dates: bool = False
    normalize_booleans: bool = False
    standardize_column_names: bool = False
    normalize_categories: bool = False
    drop_duplicates: bool = False
    duplicate_subset: list[str] | None = None
    flag_outliers: bool = False
    outlier_z: float = 3.0
    numeric_columns: list[str] | None = None
    date_columns: list[str] | None = None


@dataclass
class CleaningResult:
    frame: pd.DataFrame
    operations: list[CleaningOperation] = field(default_factory=list)
    conversion_failures: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def is_text_column(series: pd.Series) -> bool:
    """True for object/str columns across pandas 2.x and 3.x dtypes."""
    return not (
        pd.api.types.is_numeric_dtype(series)
        or pd.api.types.is_datetime64_any_dtype(series)
        or pd.api.types.is_bool_dtype(series)
        or pd.api.types.is_timedelta64_dtype(series)
    )


def _string_columns(frame: pd.DataFrame) -> list[str]:
    return [c for c in frame.columns if is_text_column(frame[c])]


def _to_number(value: Any) -> tuple[Any, bool]:
    """Return ``(converted, ok)``; ``ok`` is False when the value was not numeric."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan, True
    if isinstance(value, (int, float, np.integer, np.floating)):
        return value, True
    text = str(value).strip()
    if text in MISSING_TOKENS:
        return np.nan, True

    negative = False
    parens = _PARENS_NEGATIVE.match(text)
    if parens:
        text = parens.group(1)
        negative = True

    percent = _PERCENT.match(text)
    if percent:
        text = percent.group(1)

    currency = _CURRENCY.match(text)
    if currency and (currency.group(1) or currency.group(3)):
        text = currency.group(2)

    if not _NUMBER_LIKE.match(text):
        return value, False

    cleaned = text.replace(" ", "").replace(" ", "")
    # Decide between "1,234.56" and "1.234,56".
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif cleaned.count(",") == 1 and len(cleaned.split(",")[-1]) in {1, 2}:
        cleaned = cleaned.replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")

    try:
        number = float(cleaned)
    except ValueError:
        return value, False
    return (-number if negative else number), True


def clean(frame: pd.DataFrame, options: CleaningOptions) -> CleaningResult:
    """Apply the selected operations, returning a new frame plus a report."""
    result = frame.copy()
    operations: list[CleaningOperation] = []
    failures: dict[str, int] = {}
    warnings: list[str] = []

    if options.trim_whitespace:
        columns = _string_columns(result)
        changed = 0
        for column in columns:
            original = result[column]
            trimmed = original.map(
                lambda v: re.sub(r"\s+", " ", v).strip() if isinstance(v, str) else v
            )
            changed += int((original.astype(str) != trimmed.astype(str)).sum())
            result[column] = trimmed
        operations.append(CleaningOperation("Trim whitespace", columns, changed))

    if options.normalize_missing:
        columns = _string_columns(result)
        changed = 0
        for column in columns:
            mask = result[column].isin(MISSING_TOKENS)
            changed += int(mask.sum())
            result.loc[mask, column] = np.nan
        operations.append(
            CleaningOperation(
                "Normalize missing tokens", columns, changed, detail="e.g. '-', 'N/A', '..'"
            )
        )

    if options.numeric_conversion or options.parse_percentages or options.parse_currency:
        targets = options.numeric_columns or _numeric_candidates(result)
        converted_columns: list[str] = []
        total_changed = 0
        total_failed = 0
        for column in targets:
            if column not in result.columns:
                continue
            values, oks = (
                zip(*(_to_number(v) for v in result[column]), strict=True)
                if len(result)
                else ((), ())
            )
            failed = sum(1 for ok in oks if not ok)
            if len(result) and failed / len(result) > 0.5:
                warnings.append(
                    f"Column '{column}' was left as text: more than half of its values are not numeric."
                )
                continue
            was_percent = bool(
                options.parse_percentages
                and result[column].astype(str).str.contains("%", na=False).mean() > 0.5
            )
            series = pd.Series(list(values), index=result.index)
            if was_percent:
                series = series / 100.0
            total_changed += int(series.notna().sum())
            if failed:
                failures[column] = failed
                total_failed += failed
            result[column] = series
            converted_columns.append(column)
        if converted_columns:
            operations.append(
                CleaningOperation(
                    "Numeric conversion",
                    converted_columns,
                    total_changed,
                    total_failed,
                    "Percentages divided by 100; currency symbols and thousands separators removed."
                    if options.parse_percentages or options.parse_currency
                    else "",
                )
            )

    if options.parse_dates:
        targets = options.date_columns or _date_candidates(result)
        converted: list[str] = []
        total_failed = 0
        for column in targets:
            if column not in result.columns:
                continue
            parsed = pd.to_datetime(result[column], errors="coerce", format="mixed", utc=False)
            failed = int(parsed.isna().sum() - result[column].isna().sum())
            if len(result) and parsed.notna().mean() < 0.5:
                warnings.append(
                    f"Column '{column}' was left unchanged: fewer than half of its values parsed as dates."
                )
                continue
            if failed > 0:
                failures[column] = failures.get(column, 0) + failed
                total_failed += failed
            result[column] = parsed
            converted.append(column)
        if converted:
            operations.append(
                CleaningOperation("Parse dates", converted, int(len(result)), total_failed)
            )

    if options.normalize_booleans:
        columns: list[str] = []
        changed = 0
        for column in _string_columns(result):
            lowered = result[column].dropna().astype(str).str.strip().str.lower()
            if lowered.empty:
                continue
            if set(lowered.unique()) <= (_BOOL_TRUE | _BOOL_FALSE):
                result[column] = result[column].map(
                    lambda v: True
                    if str(v).strip().lower() in _BOOL_TRUE
                    else (False if str(v).strip().lower() in _BOOL_FALSE else np.nan)
                )
                columns.append(column)
                changed += int(result[column].notna().sum())
        if columns:
            operations.append(CleaningOperation("Normalize booleans", columns, changed))

    if options.normalize_categories:
        columns = []
        changed = 0
        for column in _string_columns(result):
            series = result[column].dropna().astype(str)
            if series.empty:
                continue
            ratio = series.nunique() / max(len(series), 1)
            if ratio < 0.5:
                normalized = result[column].map(
                    lambda v: re.sub(r"\s+", " ", str(v)).strip() if isinstance(v, str) else v
                )
                changed += int((result[column].astype(str) != normalized.astype(str)).sum())
                result[column] = normalized
                columns.append(column)
        if columns:
            operations.append(
                CleaningOperation("Normalize categories", columns, changed, detail="Whitespace only; labels preserved.")
            )

    if options.standardize_column_names:
        from ..extraction.normalizer import standardize_columns

        result, mapping = standardize_columns(result)
        renamed = [f"{old} → {new}" for old, new in mapping.items() if old != new]
        operations.append(
            CleaningOperation(
                "Standardize column names",
                list(mapping.values()),
                len(renamed),
                detail="; ".join(renamed[:6]),
            )
        )

    if options.drop_duplicates:
        from ..extraction.deduplicator import drop_duplicate_rows

        result, report = drop_duplicate_rows(result, options.duplicate_subset)
        operations.append(
            CleaningOperation(
                "Remove duplicate rows",
                options.duplicate_subset or [],
                report.removed_rows,
                detail=f"method: {report.method}",
            )
        )

    if options.flag_outliers:
        flagged: list[str] = []
        for column in result.select_dtypes(include=[np.number]).columns:
            series = result[column].astype(float)
            if series.notna().sum() < 8:
                continue
            std = series.std(ddof=0)
            if not std or np.isnan(std):
                continue
            z = (series - series.mean()).abs() / std
            flag_column = f"{column}_outlier_flag"
            result[flag_column] = z > options.outlier_z
            flagged.append(flag_column)
        if flagged:
            operations.append(
                CleaningOperation(
                    "Flag outliers",
                    flagged,
                    int(sum(result[c].sum() for c in flagged)),
                    detail=f"|z| > {options.outlier_z}. Rows are flagged, never deleted.",
                )
            )

    return CleaningResult(
        frame=result, operations=operations, conversion_failures=failures, warnings=warnings
    )


def _numeric_candidates(frame: pd.DataFrame) -> list[str]:
    """Columns whose text values mostly look numeric."""
    candidates: list[str] = []
    for column in frame.columns:
        if str(column).startswith("_") or not is_text_column(frame[column]):
            continue
        series = frame[column].dropna().astype(str).head(200)
        if series.empty:
            continue
        hits = sum(1 for value in series if _to_number(value)[1] and _NUMBER_LIKE.match(
            re.sub(r"[%$€£¥₹,\s]|USD|EUR|GBP", "", value)
        ))
        if hits / len(series) >= 0.7:
            candidates.append(column)
    return candidates


def _date_candidates(frame: pd.DataFrame) -> list[str]:
    candidates: list[str] = []
    for column in frame.columns:
        if str(column).startswith("_") or not is_text_column(frame[column]):
            continue
        name = str(column).lower()
        series = frame[column].dropna().astype(str).head(100)
        if series.empty:
            continue
        looks_dateish = sum(
            1
            for value in series
            if re.search(r"\d{4}-\d{2}-\d{2}|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}/\d{2}", value)
        )
        if looks_dateish / len(series) >= 0.6 or any(
            token in name for token in ("date", "time", "published", "updated", "تاريخ")
        ):
            candidates.append(column)
    return candidates
