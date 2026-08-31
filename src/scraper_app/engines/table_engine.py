"""HTML table engine (Tier 1).

Extracts a chosen table with pandas/lxml and follows pagination by refetching
the same table index on each page. No LLM is ever used here — that is an
explicit product rule.
"""

from __future__ import annotations

import time
from typing import Any

from ..config import SETTINGS
from ..discovery import table_detector
from ..exceptions import ErrorCode, ScraperError
from ..logging_config import RunLogger
from ..models import CandidateDataset, ExtractionRequest, ExtractionResult, ExtractionSchema
from .base import BaseEngine, detect_schema_drift
from .http_client import fetch
from .pagination_support import iter_pages


class TableEngine(BaseEngine):
    name = "table"
    label = "HTML table"
    capabilities = {"static_html", "html_tables", "pagination", "local"}
    tier = 1
    cost_mode = "free"
    reliability = 0.9
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
        table_index = int(payload.get("table_index", 0))

        all_records: list[dict[str, Any]] = []
        columns: list[str] = []
        source_urls: list[str] = []
        warnings: list[str] = []
        drift: list[str] = []
        pages_requested = 0
        pages_successful = 0
        max_rows = request.max_rows or SETTINGS.limits.max_rows

        for page in iter_pages(
            request,
            limit_pages=limit_pages,
            fetcher=lambda url: fetch(
                url,
                headers=request.options.headers or None,
                cookies=request.options.cookies or None,
                timeout=request.options.timeout,
                requests_per_second=request.options.requests_per_second,
            ),
            progress=progress,
            logger=logger,
        ):
            pages_requested += 1
            if page.error:
                if pages_successful == 0:
                    raise page.error
                warnings.append(f"Stopped at page {pages_requested}: {page.error.message()}")
                break

            _candidates, frames = table_detector.detect_tables(page.html, page.url)
            if not frames:
                if pages_successful == 0:
                    raise ScraperError(
                        ErrorCode.NO_DATA_DETECTED, "No HTML table was found on the page."
                    )
                warnings.append(f"Page {pages_requested} had no table; stopping.")
                break
            if table_index >= len(frames):
                if pages_successful == 0:
                    raise ScraperError(
                        ErrorCode.SELECTOR_NOT_FOUND,
                        f"Table {table_index + 1} does not exist on this page.",
                    )
                warnings.append(
                    f"Table {table_index + 1} was missing on page {pages_requested}; stopping."
                )
                break

            frame = frames[table_index]
            records = frame.to_dict(orient="records")
            if not records:
                break

            if not columns:
                columns = [str(c) for c in frame.columns]
            else:
                drift.extend(detect_schema_drift(records, columns))

            if request.add_provenance_columns:
                for record in records:
                    record.setdefault("_source_url", page.url)
                    record.setdefault("_source_page", page.number)

            all_records.extend(records)
            pages_successful += 1
            source_urls.append(page.url)
            if logger:
                logger.log(
                    "table",
                    "page_extracted",
                    url=page.url,
                    engine=self.name,
                    page=page.number,
                    rows=len(records),
                )

            if len(all_records) >= max_rows:
                all_records = all_records[:max_rows]
                warnings.append(f"Stopped at the row limit ({max_rows:,}).")
                break

        all_columns = list(dict.fromkeys([*columns, *(k for r in all_records for k in r)]))
        return self._result(
            success=bool(all_records),
            records=all_records,
            columns=all_columns,
            source_urls=list(dict.fromkeys(source_urls)),
            started=started,
            pages_requested=pages_requested,
            pages_successful=pages_successful,
            warnings=warnings,
            schema_drift=list(dict.fromkeys(drift))[:10],
            metadata={"table_index": table_index},
        )
