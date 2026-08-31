"""Document extraction (spec sections 4N / 100).

When a URL resolves to a PDF the app routes it here instead of forcing HTML
scraping. PyMuPDF is used when installed (text + tables per page); Docling is
recognised as the heavier optional path. Without either, the engine reports an
honest limitation rather than returning an empty dataset.
"""

from __future__ import annotations

import time
from typing import Any

from ..config import SETTINGS
from ..exceptions import ErrorCode, ScraperError
from ..logging_config import RunLogger
from ..models import CandidateDataset, ExtractionRequest, ExtractionResult, ExtractionSchema
from .base import Availability, BaseEngine
from .http_client import fetch


def _pymupdf_available() -> bool:
    try:
        import fitz  # noqa: F401  (PyMuPDF)

        return True
    except Exception:
        return False


class DocumentEngine(BaseEngine):
    name = "document"
    label = "Document (PDF)"
    capabilities = {"documents", "local"}
    tier = 1
    cost_mode = "local_compute"
    reliability = 0.7
    speed = 0.6

    def availability(self) -> Availability:
        if _pymupdf_available():
            return Availability(True)
        return Availability(
            False,
            "PDF extraction needs the optional PyMuPDF package.",
            "pip install pymupdf",
        )

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
        status = self.availability()
        if not status.ready:
            raise ScraperError(
                ErrorCode.OPTIONAL_ENGINE_NOT_INSTALLED,
                status.reason,
                {"install_hint": status.install_hint},
            )

        payload = (candidate.payload if candidate else {}) or {}
        url = str(payload.get("url") or request.url)
        response = fetch(url, max_bytes=SETTINGS.limits.max_download_bytes)

        import fitz  # type: ignore

        records: list[dict[str, Any]] = []
        tables_found = 0
        with fitz.open(stream=response.content, filetype="pdf") as document:
            page_limit = min(limit_pages or request.max_pages or document.page_count, document.page_count)
            for index in range(page_limit):
                if progress:
                    progress(index + 1, page_limit, url)
                page = document.load_page(index)
                text = page.get_text("text") or ""
                page_tables: list[list[list[str]]] = []
                try:
                    finder = page.find_tables()
                    page_tables = [table.extract() for table in finder.tables]
                except Exception:
                    page_tables = []
                tables_found += len(page_tables)

                if page_tables:
                    for table_index, table in enumerate(page_tables):
                        if len(table) < 2:
                            continue
                        header = [str(cell or f"column_{i}") for i, cell in enumerate(table[0])]
                        for row in table[1:]:
                            record = {
                                header[i] if i < len(header) else f"column_{i}": (cell or "")
                                for i, cell in enumerate(row)
                            }
                            record["_page"] = index + 1
                            record["_table"] = table_index + 1
                            records.append(record)
                else:
                    records.append({"page": index + 1, "text": text.strip()})

        if not records:
            raise ScraperError(ErrorCode.NO_DATA_DETECTED, "The document contained no readable text.")

        if request.add_provenance_columns:
            for record in records:
                record.setdefault("_source_url", response.url)

        if logger:
            logger.log("document", "pdf_extracted", url=response.url, engine=self.name, rows=len(records))

        return self._result(
            success=True,
            records=records[: request.max_rows or SETTINGS.limits.max_rows],
            columns=list(dict.fromkeys(key for record in records for key in record)),
            source_urls=[response.url],
            started=started,
            pages_requested=1,
            pages_successful=1,
            metadata={"tables_found": tables_found, "parser": "pymupdf"},
        )
