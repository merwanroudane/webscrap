"""Unified engine contract (spec section 54).

Every engine — built-in or optional adapter — implements the same interface,
returns the same :class:`ExtractionResult`, and reports availability without
ever raising an ``ImportError`` into the application.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from ..logging_config import RunLogger
from ..models import (
    CandidateDataset,
    EngineProbe,
    ExtractionRequest,
    ExtractionResult,
    ExtractionSchema,
    utcnow,
)

# Capability vocabulary used by the registry and router (spec section 56).
CAPABILITIES = {
    "static_html",
    "html_tables",
    "json",
    "xml",
    "rss",
    "files",
    "documents",
    "javascript",
    "network_capture",
    "pagination",
    "crawl",
    "semantic_extraction",
    "natural_language_actions",
    "structured_output",
    "hosted",
    "local",
}


class Availability:
    """Why an engine can or cannot run right now."""

    def __init__(self, ready: bool, reason: str = "", install_hint: str = "") -> None:
        self.ready = ready
        self.reason = reason
        self.install_hint = install_hint

    def __bool__(self) -> bool:  # pragma: no cover - trivial
        return self.ready


class BaseEngine(ABC):
    """Interface every extraction engine implements."""

    name: str = "base"
    label: str = "Base engine"
    capabilities: set[str] = set()
    tier: int = 1
    cost_mode: str = "free"  # free | local_compute | metered
    deterministic: bool = True
    requires_package: str | None = None
    requires_credentials: str | None = None
    reliability: float = 0.7
    speed: float = 0.7

    def availability(self) -> Availability:
        """Default: available when the required package imports cleanly."""
        if self.requires_package:
            try:
                __import__(self.requires_package)
            except Exception:
                return Availability(
                    False,
                    f"The optional package '{self.requires_package}' is not installed.",
                    f"pip install {self.requires_package}",
                )
        if self.requires_credentials:
            from ..config import has_credentials

            if not has_credentials(self.requires_credentials):
                return Availability(
                    False,
                    "API key not configured.",
                    f"Add the {self.requires_credentials.upper()} key to your .env file.",
                )
        return Availability(True)

    def available(self) -> bool:
        return bool(self.availability())

    def probe(
        self, request: ExtractionRequest, candidate: CandidateDataset | None = None
    ) -> EngineProbe:
        """Cheap feasibility check. Engines override when a real probe helps."""
        status = self.availability()
        return EngineProbe(
            engine=self.name,
            available=status.ready,
            good_enough=status.ready and candidate is not None,
            score=candidate.score if candidate else 0.0,
            reason=status.reason,
        )

    @abstractmethod
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
        """Run the extraction and return the unified result."""

    # ------------------------------------------------------------------ helpers
    def _result(
        self,
        *,
        success: bool,
        records: list[dict[str, Any]] | None = None,
        columns: list[str] | None = None,
        source_urls: list[str] | None = None,
        started: float | None = None,
        **extra: Any,
    ) -> ExtractionResult:
        records = records or []
        columns = columns or (list(records[0].keys()) if records else [])
        return ExtractionResult(
            success=success,
            engine=self.name,
            records=records,
            columns=columns,
            source_urls=source_urls or [],
            rows=len(records),
            finished_at=utcnow(),
            elapsed_ms=int((time.monotonic() - started) * 1000) if started else 0,
            **extra,
        )


def records_to_frame(
    records: list[dict[str, Any]], columns: list[str] | None = None
) -> pd.DataFrame:
    """Build a DataFrame with a stable column order across heterogeneous rows."""
    if not records:
        return pd.DataFrame(columns=columns or [])
    ordered: list[str] = list(columns or [])
    for record in records:
        for key in record:
            if key not in ordered:
                ordered.append(key)
    return pd.DataFrame([{key: record.get(key) for key in ordered} for record in records])


def detect_schema_drift(records: list[dict[str, Any]], baseline: list[str]) -> list[str]:
    """Report new/missing columns across pages (spec section 63)."""
    if not records or not baseline:
        return []
    baseline_set = set(baseline)
    seen: set[str] = set()
    for record in records:
        seen.update(record.keys())
    messages: list[str] = []
    new = sorted(seen - baseline_set)
    missing = sorted(baseline_set - seen)
    if new:
        messages.append(f"New fields appeared on later pages: {', '.join(new[:8])}")
    if missing:
        messages.append(f"Expected fields were absent on some pages: {', '.join(missing[:8])}")
    return messages
