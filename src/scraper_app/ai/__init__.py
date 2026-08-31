"""Optional AI layer.

Importing this package must never fail and must never require an API key.
Use :func:`scraper_app.ai.service.get_provider` to discover whether any model
is actually usable.
"""

from .base import AIAvailability, AIMode, Completion, LLMProvider, Usage
from .service import (
    AIUsageLog,
    ai_enabled,
    available_providers,
    describe_variables,
    extract_records,
    get_provider,
    map_fields,
    propose_schema,
    provider_table,
    providers,
    review_extraction,
)
from .structured import StructuredResult, call_structured, evidence_ratio

__all__ = [
    "AIAvailability",
    "AIMode",
    "AIUsageLog",
    "Completion",
    "LLMProvider",
    "StructuredResult",
    "Usage",
    "ai_enabled",
    "available_providers",
    "call_structured",
    "describe_variables",
    "evidence_ratio",
    "extract_records",
    "get_provider",
    "map_fields",
    "propose_schema",
    "provider_table",
    "providers",
    "review_extraction",
]
