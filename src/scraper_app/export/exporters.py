"""Export layer (spec sections 13, 14).

Two rules drive this module:

1. a format is offered only when the environment can produce it *and* the
   current dataset can be represented in it;
2. when a format cannot safely represent the data, the user sees a clear
   limitation instead of a corrupt file.
"""

from __future__ import annotations

import io
import re
import sqlite3
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ..exceptions import ErrorCode, ScraperError


@dataclass
class FormatSupport:
    ok: bool
    reason: str = ""
    install_hint: str = ""


@dataclass
class ExportFormat:
    key: str
    label: str
    extension: str
    mime: str
    category: str  # common | research | database | reproducible
    builder: Callable[[pd.DataFrame], bytes]
    check: Callable[[pd.DataFrame], FormatSupport]
    note: str = ""


def _package_available(module: str) -> bool:
    try:
        __import__(module)
        return True
    except Exception:
        return False


def _flatten_for_export(frame: pd.DataFrame) -> pd.DataFrame:
    """Stringify nested values that only tabular-native formats can hold."""
    result = frame.copy()
    for column in result.columns:
        if not pd.api.types.is_numeric_dtype(result[column]) and not pd.api.types.is_datetime64_any_dtype(result[column]):
            result[column] = result[column].map(
                lambda v: str(v) if isinstance(v, (dict, list, set, tuple)) else v
            )
    return result


# ------------------------------------------------------------------ capability checks
def _always(frame: pd.DataFrame) -> FormatSupport:
    if frame is None or frame.empty:
        return FormatSupport(False, "The dataset is empty.")
    return FormatSupport(True)


def _check_excel(frame: pd.DataFrame) -> FormatSupport:
    base = _always(frame)
    if not base.ok:
        return base
    if not (_package_available("xlsxwriter") or _package_available("openpyxl")):
        return FormatSupport(False, "Excel export needs xlsxwriter or openpyxl.", "pip install xlsxwriter")
    if len(frame) > 1_048_575:
        return FormatSupport(False, "Excel supports at most 1,048,575 data rows. Use CSV or Parquet.")
    if frame.shape[1] > 16_384:
        return FormatSupport(False, "Excel supports at most 16,384 columns.")
    return FormatSupport(True)


def _check_parquet(frame: pd.DataFrame) -> FormatSupport:
    base = _always(frame)
    if not base.ok:
        return base
    if not _package_available("pyarrow"):
        return FormatSupport(False, "Parquet export needs pyarrow.", "pip install pyarrow")
    return FormatSupport(True)


def _check_stata(frame: pd.DataFrame) -> FormatSupport:
    base = _always(frame)
    if not base.ok:
        return base
    invalid = [c for c in frame.columns if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,31}", str(c))]
    if invalid:
        return FormatSupport(
            False,
            "Stata needs column names of at most 32 characters using letters, digits and underscore. "
            f"Problem columns: {', '.join(str(c) for c in invalid[:5])}. "
            "Enable 'Standardize column names' in Clean & Validate first.",
        )
    if any(pd.api.types.is_datetime64tz_dtype(frame[c]) for c in frame.columns):
        return FormatSupport(
            False, "Stata cannot store timezone-aware datetimes. Convert them or export CSV/Parquet."
        )
    return FormatSupport(True)


def _check_spss(frame: pd.DataFrame) -> FormatSupport:
    base = _always(frame)
    if not base.ok:
        return base
    if not _package_available("pyreadstat"):
        return FormatSupport(False, "SPSS export needs pyreadstat.", "pip install pyreadstat")
    # SPSS variable names must begin with a letter: the provenance columns
    # (_source_url, ...) are the usual reason this format is unavailable.
    invalid = [c for c in frame.columns if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.@$#]{0,63}", str(c))]
    if invalid:
        provenance = [c for c in invalid if str(c).startswith("_")]
        hint = (
            " Turn off 'Add source columns' before extracting, or apply "
            "'Standardize column names' in Clean & Validate."
            if provenance
            else ""
        )
        return FormatSupport(
            False,
            "SPSS variable names must start with a letter and avoid spaces/symbols. "
            f"Problem columns: {', '.join(str(c) for c in invalid[:5])}.{hint}",
        )
    return FormatSupport(True)


def _check_rds(frame: pd.DataFrame) -> FormatSupport:
    base = _always(frame)
    if not base.ok:
        return base
    if not _package_available("pyreadr"):
        return FormatSupport(
            False,
            "RDS export needs the optional pyreadr package (AGPL-3.0). "
            "Exporting CSV or Parquet and reading it in R avoids that licence.",
            "pip install pyreadr",
        )
    return FormatSupport(True)


def _check_duckdb(frame: pd.DataFrame) -> FormatSupport:
    base = _always(frame)
    if not base.ok:
        return base
    if not _package_available("duckdb"):
        return FormatSupport(False, "DuckDB export needs the duckdb package.", "pip install duckdb")
    return FormatSupport(True)


# ------------------------------------------------------------------------- builders
def to_csv(frame: pd.DataFrame) -> bytes:
    return _flatten_for_export(frame).to_csv(index=False).encode("utf-8-sig")


def to_tsv(frame: pd.DataFrame) -> bytes:
    return _flatten_for_export(frame).to_csv(index=False, sep="\t").encode("utf-8-sig")


def to_excel(frame: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    engine = "xlsxwriter" if _package_available("xlsxwriter") else "openpyxl"
    export = _flatten_for_export(frame)
    for column in export.columns:
        if pd.api.types.is_datetime64tz_dtype(export[column]):
            export[column] = export[column].dt.tz_localize(None)
    with pd.ExcelWriter(buffer, engine=engine) as writer:
        export.to_excel(writer, index=False, sheet_name="data")
    return buffer.getvalue()


def to_json(frame: pd.DataFrame) -> bytes:
    return _flatten_for_export(frame).to_json(orient="records", force_ascii=False, indent=2).encode("utf-8")


def to_jsonl(frame: pd.DataFrame) -> bytes:
    return _flatten_for_export(frame).to_json(orient="records", force_ascii=False, lines=True).encode("utf-8")


def to_parquet(frame: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    _flatten_for_export(frame).to_parquet(buffer, index=False)
    return buffer.getvalue()


def to_feather(frame: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    _flatten_for_export(frame).reset_index(drop=True).to_feather(buffer)
    return buffer.getvalue()


def to_stata(frame: pd.DataFrame) -> bytes:
    export = _flatten_for_export(frame)
    for column in export.columns:
        if pd.api.types.is_datetime64tz_dtype(export[column]):
            export[column] = export[column].dt.tz_localize(None)
        elif not pd.api.types.is_numeric_dtype(export[column]):
            export[column] = export[column].astype(str).replace("nan", "")
    buffer = io.BytesIO()
    export.to_stata(buffer, write_index=False, version=118)
    return buffer.getvalue()


def to_spss(frame: pd.DataFrame) -> bytes:
    import pyreadstat  # type: ignore

    export = _flatten_for_export(frame)
    for column in export.columns:
        if pd.api.types.is_datetime64tz_dtype(export[column]):
            export[column] = export[column].dt.tz_localize(None)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "dataset.sav"
        pyreadstat.write_sav(export, str(path))
        return path.read_bytes()


def to_rds(frame: pd.DataFrame) -> bytes:
    import pyreadr  # type: ignore

    export = _flatten_for_export(frame)
    for column in export.columns:
        if pd.api.types.is_datetime64tz_dtype(export[column]):
            export[column] = export[column].dt.tz_localize(None)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "dataset.rds"
        pyreadr.write_rds(str(path), export)
        return path.read_bytes()


def to_sqlite(frame: pd.DataFrame, table: str = "dataset") -> bytes:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "dataset.sqlite"
        connection = sqlite3.connect(path)
        try:
            _flatten_for_export(frame).to_sql(table, connection, index=False, if_exists="replace")
            connection.commit()
        finally:
            connection.close()
        return path.read_bytes()


def to_duckdb(frame: pd.DataFrame, table: str = "dataset") -> bytes:
    import duckdb  # type: ignore

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "dataset.duckdb"
        connection = duckdb.connect(str(path))
        try:
            export = _flatten_for_export(frame)  # noqa: F841 - referenced by the SQL below
            connection.execute(f"CREATE TABLE {table} AS SELECT * FROM export")
        finally:
            connection.close()
        return path.read_bytes()


def to_html(frame: pd.DataFrame) -> bytes:
    return _flatten_for_export(frame).to_html(index=False, border=0).encode("utf-8")


def to_markdown(frame: pd.DataFrame) -> bytes:
    export = _flatten_for_export(frame)
    try:
        return export.to_markdown(index=False).encode("utf-8")
    except Exception:
        return export.to_string(index=False).encode("utf-8")


FORMATS: list[ExportFormat] = [
    ExportFormat("csv", "CSV", ".csv", "text/csv", "common", to_csv, _always),
    ExportFormat("xlsx", "Excel", ".xlsx",
                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                 "common", to_excel, _check_excel),
    ExportFormat("parquet", "Parquet", ".parquet", "application/octet-stream", "common",
                 to_parquet, _check_parquet),
    ExportFormat("json", "JSON", ".json", "application/json", "common", to_json, _always),
    ExportFormat("jsonl", "JSON Lines", ".jsonl", "application/x-ndjson", "common", to_jsonl, _always),
    ExportFormat("tsv", "TSV", ".tsv", "text/tab-separated-values", "common", to_tsv, _always),
    ExportFormat("feather", "Feather", ".feather", "application/octet-stream", "common",
                 to_feather, _check_parquet),
    ExportFormat("dta", "Stata (.dta)", ".dta", "application/octet-stream", "research",
                 to_stata, _check_stata, "Stata 14+ format (version 118)."),
    ExportFormat("sav", "SPSS (.sav)", ".sav", "application/octet-stream", "research",
                 to_spss, _check_spss),
    ExportFormat("rds", "R (.rds)", ".rds", "application/octet-stream", "research",
                 to_rds, _check_rds),
    ExportFormat("sqlite", "SQLite", ".sqlite", "application/vnd.sqlite3", "database",
                 to_sqlite, _always),
    ExportFormat("duckdb", "DuckDB", ".duckdb", "application/octet-stream", "database",
                 to_duckdb, _check_duckdb),
    ExportFormat("html", "HTML table", ".html", "text/html", "common", to_html, _always),
    ExportFormat("md", "Markdown table", ".md", "text/markdown", "common", to_markdown, _always),
]

FORMATS_BY_KEY = {fmt.key: fmt for fmt in FORMATS}


def build(frame: pd.DataFrame, key: str) -> bytes:
    """Build one export, raising a taxonomy error when it is not representable."""
    fmt = FORMATS_BY_KEY.get(key)
    if fmt is None:
        raise ScraperError(ErrorCode.EXPORT_FORMAT_LIMITATION, f"Unknown format '{key}'.")
    support = fmt.check(frame)
    if not support.ok:
        raise ScraperError(ErrorCode.EXPORT_FORMAT_LIMITATION, support.reason)
    return fmt.builder(frame)


def available_formats(frame: pd.DataFrame) -> list[tuple[ExportFormat, FormatSupport]]:
    return [(fmt, fmt.check(frame)) for fmt in FORMATS]
