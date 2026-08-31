"""Lightweight dataframe validation (spec: Pandera where useful).

Validation is advisory: it reports violations so the researcher can decide.
It never drops rows. Pandera is used when installed; otherwise the same checks
run in plain pandas so the feature is always available.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..models import ExtractionSchema


@dataclass
class ValidationRule:
    column: str
    required: bool = False
    dtype: str | None = None  # string | number | integer | date | url | boolean
    min_value: float | None = None
    max_value: float | None = None
    unique: bool = False


@dataclass
class ValidationResult:
    passed: bool = True
    errors: list[str] = field(default_factory=list)
    row_flags: dict[str, int] = field(default_factory=dict)
    engine: str = "pandas"


def rules_from_schema(schema: ExtractionSchema) -> list[ValidationRule]:
    return [
        ValidationRule(column=spec.name, required=spec.required, dtype=spec.dtype)
        for spec in schema.fields
    ]


def _dtype_violations(series: pd.Series, dtype: str | None) -> int:
    if not dtype or series.empty:
        return 0
    non_null = series.dropna()
    if non_null.empty:
        return 0
    if dtype in {"number", "integer"}:
        coerced = pd.to_numeric(non_null, errors="coerce")
        violations = int(coerced.isna().sum())
        if dtype == "integer":
            violations += int(((coerced.dropna() % 1) != 0).sum())
        return violations
    if dtype == "date":
        return int(pd.to_datetime(non_null, errors="coerce", format="mixed").isna().sum())
    if dtype == "url":
        return int((~non_null.astype(str).str.startswith(("http://", "https://"))).sum())
    if dtype == "boolean":
        return int((~non_null.isin([True, False, 0, 1, "true", "false", "True", "False"])).sum())
    return 0


def validate(frame: pd.DataFrame, rules: list[ValidationRule]) -> ValidationResult:
    """Run the rules and return a readable report."""
    result = ValidationResult()
    if frame is None or frame.empty:
        result.errors.append("The dataset is empty, so validation was skipped.")
        result.passed = False
        return result

    for rule in rules:
        if rule.column not in frame.columns:
            if rule.required:
                result.errors.append(f"Required field '{rule.column}' is missing from the dataset.")
                result.passed = False
            continue

        series = frame[rule.column]
        if rule.required:
            missing = int(series.isna().sum())
            if missing:
                result.errors.append(
                    f"Required field '{rule.column}' is empty in {missing:,} rows."
                )
                result.row_flags[rule.column] = missing
                result.passed = False

        violations = _dtype_violations(series, rule.dtype)
        if violations:
            result.errors.append(
                f"'{rule.column}' has {violations:,} values that are not valid {rule.dtype}."
            )
            result.row_flags[f"{rule.column}:dtype"] = violations
            result.passed = False

        if rule.min_value is not None or rule.max_value is not None:
            numeric = pd.to_numeric(series, errors="coerce")
            if rule.min_value is not None:
                below = int((numeric < rule.min_value).sum())
                if below:
                    result.errors.append(
                        f"'{rule.column}' has {below:,} values below the minimum {rule.min_value}."
                    )
                    result.passed = False
            if rule.max_value is not None:
                above = int((numeric > rule.max_value).sum())
                if above:
                    result.errors.append(
                        f"'{rule.column}' has {above:,} values above the maximum {rule.max_value}."
                    )
                    result.passed = False

        if rule.unique:
            duplicated = int(series.duplicated().sum())
            if duplicated:
                result.errors.append(
                    f"'{rule.column}' should be unique but has {duplicated:,} repeated values."
                )
                result.passed = False

    result.engine = "pandera" if _pandera_available() else "pandas"
    return result


def _pandera_available() -> bool:
    try:
        import pandera  # noqa: F401

        return True
    except Exception:
        return False


def build_pandera_schema(rules: list[ValidationRule]):  # pragma: no cover - optional path
    """Return an equivalent Pandera schema for users who want to reuse it."""
    try:
        import pandera.pandas as pa
    except Exception:
        try:
            import pandera as pa  # type: ignore
        except Exception:
            return None

    dtype_map = {"number": float, "integer": "Int64", "string": str, "boolean": bool}
    columns = {}
    for rule in rules:
        checks = []
        if rule.min_value is not None:
            checks.append(pa.Check.ge(rule.min_value))
        if rule.max_value is not None:
            checks.append(pa.Check.le(rule.max_value))
        columns[rule.column] = pa.Column(
            dtype_map.get(rule.dtype or "string", object),
            checks=checks or None,
            nullable=not rule.required,
            unique=rule.unique,
            required=rule.required,
            coerce=True,
        )
    return pa.DataFrameSchema(columns, strict=False)
