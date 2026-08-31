"""Prompt text used by the AI layer, kept separate from the calling code.

Every prompt here is paired with a Pydantic schema in :mod:`scraper_app.ai.models`
and is sent through :func:`scraper_app.ai.structured.call_structured`, which
wraps page content as untrusted data and validates the reply.
"""

from __future__ import annotations

FIELD_PROPOSAL = (
    "Propose the dataset columns a researcher could extract from this page. "
    "Use snake_case names. For each field copy one supporting value from the "
    "excerpt into 'evidence'. Propose nothing you cannot see."
)

SEMANTIC_EXTRACTION = (
    "Extract the requested records from the excerpt. Return one object per row "
    "and copy values verbatim. Do not compute, translate or infer values."
)

FIELD_MAPPING = (
    "Map each requested research field to the column that holds it. Use null "
    "for a requested field that no column provides."
)

EXTRACTION_REVIEW = (
    "Review this extracted sample for obvious problems: shifted columns, merged "
    "values, headers used as data, or values that do not match their column name."
)

DATA_DICTIONARY = (
    "Write a short human label, a unit where one is evident, and a brief note "
    "for each variable. Leave a field empty rather than guessing."
)

__all__ = [
    "DATA_DICTIONARY",
    "EXTRACTION_REVIEW",
    "FIELD_MAPPING",
    "FIELD_PROPOSAL",
    "SEMANTIC_EXTRACTION",
]
