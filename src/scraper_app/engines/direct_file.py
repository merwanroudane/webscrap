"""Direct data-file engine (Tier 0).

Reads a published CSV/TSV/JSON/JSONL/Excel/Parquet/Feather/Stata/SPSS file
straight into a DataFrame. This is always the preferred route when the URL
resolves to a dataset file.
"""

from __future__ import annotations

import io
import json
import time
import zipfile
from typing import Any

import pandas as pd

from ..config import SETTINGS
from ..discovery import file_detector
from ..exceptions import ErrorCode, ScraperError
from ..logging_config import RunLogger
from ..models import CandidateDataset, ExtractionRequest, ExtractionResult, ExtractionSchema
from .base import BaseEngine
from .http_client import fetch

_MAX_ROWS_PREVIEW = SETTINGS.limits.max_rows


def read_bytes_as_frame(payload: bytes, fmt: str, source_name: str = "") -> pd.DataFrame:
    """Parse downloaded bytes into a DataFrame according to ``fmt``."""
    buffer = io.BytesIO(payload)
    if fmt == "csv":
        return pd.read_csv(buffer, sep=None, engine="python", nrows=_MAX_ROWS_PREVIEW)
    if fmt == "tsv":
        return pd.read_csv(buffer, sep="\t", nrows=_MAX_ROWS_PREVIEW)
    if fmt == "text":
        return pd.read_csv(buffer, sep=None, engine="python", nrows=_MAX_ROWS_PREVIEW)
    if fmt == "excel":
        return pd.read_excel(buffer)
    if fmt == "parquet":
        return pd.read_parquet(buffer)
    if fmt == "feather":
        return pd.read_feather(buffer)
    if fmt == "stata":
        return pd.read_stata(buffer)
    if fmt == "spss":
        return pd.read_spss(buffer)
    if fmt == "jsonl":
        rows = [
            json.loads(line)
            for line in payload.decode("utf-8", errors="replace").splitlines()
            if line.strip()
        ]
        return pd.json_normalize(rows)
    if fmt == "json":
        data = json.loads(payload.decode("utf-8", errors="replace"))
        if isinstance(data, list):
            return pd.json_normalize(data)
        if isinstance(data, dict):
            from ..discovery.structured_data import find_record_arrays

            arrays = find_record_arrays(data)
            if arrays:
                path = arrays[0]["path"]
                node: Any = data
                if path not in ("$", ""):
                    for part in path.replace("]", "").split("."):
                        if "[" in part:
                            key, _, index = part.partition("[")
                            node = node[key][int(index)] if key else node[int(index)]
                        elif part:
                            node = node[part]
                return pd.json_normalize(node)
            return pd.json_normalize([data])
    if fmt == "xml":
        return pd.read_xml(io.BytesIO(payload))
    if fmt == "zip":
        return _read_zip(payload)
    raise ScraperError(
        ErrorCode.CONTENT_UNSUPPORTED,
        f"No reader for format '{fmt}'" + (f" ({source_name})" if source_name else ""),
    )


def _read_zip(payload: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = [
            name
            for name in archive.namelist()
            if file_detector.is_tabular_format(file_detector.format_from_url(name))
        ]
        if not members:
            raise ScraperError(
                ErrorCode.CONTENT_UNSUPPORTED, "The ZIP archive contains no readable data file."
            )
        member = members[0]
        fmt = file_detector.format_from_url(member) or "csv"
        return read_bytes_as_frame(archive.read(member), fmt, member)


class DirectFileEngine(BaseEngine):
    name = "direct_file"
    label = "Direct data file"
    capabilities = {"files", "local"}
    tier = 0
    cost_mode = "free"
    reliability = 0.95
    speed = 0.9

    def extract(
        self,
        request: ExtractionRequest,
        candidate: CandidateDataset | None = None,
        schema: ExtractionSchema | None = None,
        *,
        logger: RunLogger | None = None,
        progress=None,
        limit_pages: int | None = None,
    ) -> ExtractionResult:
        started = time.monotonic()
        payload = (candidate.payload if candidate else {}) or {}
        url = str(payload.get("url") or request.url)
        fmt = payload.get("format")

        response = fetch(url, max_bytes=SETTINGS.limits.max_download_bytes)
        fmt = fmt or file_detector.detect_format(response.url, response.content_type) or "csv"
        if logger:
            logger.log("direct_file", "downloaded", url=response.url, engine=self.name, format=fmt)

        if file_detector.is_document_format(fmt):
            raise ScraperError(
                ErrorCode.CONTENT_UNSUPPORTED,
                "This is a document, not a dataset. Use the document extraction option.",
            )

        frame = read_bytes_as_frame(response.content, str(fmt), response.url)
        frame = frame.head(request.max_rows or SETTINGS.limits.max_rows)
        records = frame.to_dict(orient="records")

        warnings: list[str] = []
        if response.truncated:
            warnings.append(
                "The download hit the configured size limit, so the dataset may be incomplete."
            )

        return self._result(
            success=True,
            records=records,
            columns=[str(c) for c in frame.columns],
            source_urls=[response.url],
            started=started,
            pages_requested=1,
            pages_successful=1,
            warnings=warnings,
            metadata={"format": fmt, "content_type": response.content_type},
        )
