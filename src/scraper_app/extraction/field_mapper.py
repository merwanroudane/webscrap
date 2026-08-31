"""Map a requested schema onto the columns a source actually provides.

Never invents data: unmatched requested fields are reported so the UI can ask
the researcher to review the mapping instead of silently producing empty
columns (spec sections 25 and 61).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

import pandas as pd

from ..extraction.schema_builder import TERM_MAP
from ..models import Confidence, ExtractionSchema

_NON_WORD = re.compile(r"[^0-9a-z؀-ۿ]+")


def _fuzzy_best(target: str, candidates: list[str]) -> tuple[str | None, float]:
    """Best fuzzy match. Uses rapidfuzz when installed, difflib otherwise."""
    if not candidates:
        return None, 0.0
    try:
        from rapidfuzz import process as rf_process

        match = rf_process.extractOne(target, candidates, score_cutoff=82)
        return (match[0], match[1] / 100.0) if match else (None, 0.0)
    except Exception:
        close = difflib.get_close_matches(target, candidates, n=1, cutoff=0.82)
        if not close:
            return None, 0.0
        ratio = difflib.SequenceMatcher(None, target, close[0]).ratio()
        return close[0], ratio

#: Reverse index: canonical name -> every phrase that maps to it.
_SYNONYMS: dict[str, set[str]] = {}
for _phrase, (_canonical, _dtype) in TERM_MAP.items():
    _SYNONYMS.setdefault(_canonical, set()).add(_phrase.lower())


def normalize(name: str) -> str:
    return _NON_WORD.sub("_", str(name).strip().lower()).strip("_")


@dataclass
class FieldMapping:
    requested: str
    matched_column: str | None
    confidence: Confidence
    method: str
    sample: str | None = None


@dataclass
class MappingReport:
    mappings: list[FieldMapping] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)
    extra_columns: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return bool(self.unmatched) or any(m.confidence is Confidence.LOW for m in self.mappings)


def map_schema(
    schema: ExtractionSchema, columns: list[str], frame: pd.DataFrame | None = None
) -> MappingReport:
    """Match requested field names against available columns."""
    report = MappingReport()
    if not schema.fields:
        report.extra_columns = list(columns)
        return report

    normalized = {normalize(column): column for column in columns}
    used: set[str] = set()

    for spec in schema.fields:
        target = normalize(spec.name)
        matched: str | None = None
        method = ""
        confidence = Confidence.LOW

        if target in normalized:
            matched, method, confidence = normalized[target], "exact", Confidence.HIGH
        else:
            for synonym in _SYNONYMS.get(spec.name, set()):
                key = normalize(synonym)
                if key in normalized:
                    matched, method, confidence = normalized[key], "synonym", Confidence.HIGH
                    break

        if matched is None:
            for key, column in normalized.items():
                if key.startswith(target) or target in key.split("_") or key in target:
                    matched, method, confidence = column, "substring", Confidence.MEDIUM
                    break

        if matched is None:
            best, _score = _fuzzy_best(target, list(normalized))
            if best:
                matched, method, confidence = normalized[best], "fuzzy", Confidence.LOW

        sample: str | None = None
        if matched and frame is not None and matched in frame.columns:
            non_null = frame[matched].dropna()
            if not non_null.empty:
                sample = str(non_null.iloc[0])[:80]

        if matched:
            used.add(matched)
            report.mappings.append(FieldMapping(spec.name, matched, confidence, method, sample))
        else:
            report.mappings.append(FieldMapping(spec.name, None, Confidence.LOW, "none"))
            report.unmatched.append(spec.name)

    report.extra_columns = [c for c in columns if c not in used and not c.startswith("_")]
    return report


def apply_mapping(
    frame: pd.DataFrame, report: MappingReport, keep_extra: bool = True
) -> pd.DataFrame:
    """Rename matched columns to the requested names, keeping provenance columns."""
    rename = {
        mapping.matched_column: mapping.requested
        for mapping in report.mappings
        if mapping.matched_column and mapping.matched_column != mapping.requested
    }
    result = frame.rename(columns=rename)

    requested = [m.requested for m in report.mappings if m.matched_column]
    provenance = [c for c in result.columns if str(c).startswith("_")]
    if keep_extra:
        ordered = (
            requested
            + [c for c in result.columns if c not in requested and c not in provenance]
            + provenance
        )
    else:
        ordered = requested + provenance
    return result[[c for c in ordered if c in result.columns]]
