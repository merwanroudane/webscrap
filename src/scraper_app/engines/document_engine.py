"""Document extraction engine (audit section Q).

Delegates to a :class:`~scraper_app.providers.documents.DocumentExtractor`:
PyMuPDF for ordinary PDFs, Docling when installed and preferred for complex
layouts. Both are local, so a document never leaves the machine.
"""

from __future__ import annotations

import time
from typing import Any

from ..config import SETTINGS
from ..exceptions import ErrorCode, ScraperError
from ..logging_config import RunLogger
from ..models import CandidateDataset, ExtractionRequest, ExtractionResult, ExtractionSchema
from ..providers import documents as document_providers
from .base import Availability, BaseEngine
from .http_client import fetch


class DocumentEngine(BaseEngine):
    name = "document"
    label = "Document (PDF)"
    capabilities = {"documents", "local"}
    tier = 1
    cost_mode = "local_compute"
    reliability = 0.7
    speed = 0.6

    def availability(self) -> Availability:
        extractor = document_providers.best_extractor()
        if extractor is not None:
            return Availability(True)
        return Availability(
            False,
            "PDF extraction needs an optional document parser.",
            "pip install pymupdf   (or: pip install docling)",
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
        extractor = document_providers.best_extractor(request.engine_preference)
        if extractor is None:
            status = self.availability()
            raise ScraperError(
                ErrorCode.OPTIONAL_ENGINE_NOT_INSTALLED,
                status.reason,
                {"install_hint": status.install_hint},
            )

        payload = (candidate.payload if candidate else {}) or {}
        url = str(payload.get("url") or request.url)
        response = fetch(url, max_bytes=SETTINGS.limits.max_download_bytes)

        if progress:
            progress(1, 1, url)

        result = extractor.extract(
            response.content,
            url=response.url,
            max_pages=limit_pages or request.max_pages or None,
        )
        records: list[dict[str, Any]] = result.to_records()
        if not records:
            raise ScraperError(
                ErrorCode.NO_DATA_DETECTED, "The document contained no readable text or tables."
            )

        if request.add_provenance_columns:
            for record in records:
                record.setdefault("_source_url", response.url)

        max_rows = request.max_rows or SETTINGS.limits.max_rows
        truncated = len(records) > max_rows
        records = records[:max_rows]

        if logger:
            logger.log(
                "document",
                "document_extracted",
                url=response.url,
                engine=self.name,
                extractor=extractor.id,
                rows=len(records),
            )

        return self._result(
            success=True,
            records=records,
            columns=list(dict.fromkeys(key for record in records for key in record)),
            source_urls=[response.url],
            started=started,
            pages_requested=1,
            pages_successful=1,
            truncated=truncated,
            metadata={
                "extractor": extractor.id,
                "pages": len(result.pages),
                "tables_found": result.table_count,
                "document_metadata": {k: str(v)[:200] for k, v in (result.metadata or {}).items()},
            },
        )
