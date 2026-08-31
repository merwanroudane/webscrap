"""The AI facade the rest of the application uses (audit section C).

Every entry point here is a no-op that returns ``None`` when AI is disabled,
no provider is installed, or no key is configured. Callers therefore never
need to branch on availability: the deterministic path simply continues.

Preferred pattern, enforced by the callers:

    sample pages → AI proposes a schema/strategy once → validate against
    evidence → deterministic extraction for the remaining pages → AI re-enters
    only on schema drift or extraction failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models import Confidence, ExtractionSchema, FieldSpec, NameSource
from .base import AIMode, LLMProvider, Usage
from .models import (
    DataDictionaryProposal,
    ExtractedRecords,
    FieldMappingProposal,
    ProposedSchema,
    ValidationVerdict,
)
from .providers.anthropic_provider import AnthropicProvider
from .providers.google_provider import GoogleProvider
from .providers.litellm_provider import LiteLLMProvider
from .providers.openai_provider import OpenAIProvider
from .structured import call_structured, evidence_ratio

#: Order matters: the first configured provider wins when none is requested.
PROVIDER_ORDER: list[type[LLMProvider]] = [
    AnthropicProvider,
    OpenAIProvider,
    GoogleProvider,
    LiteLLMProvider,
]

#: A proposal is rejected when fewer than this fraction of its values appear
#: in the page content the model was shown.
MIN_EVIDENCE_RATIO = 0.5


@dataclass
class AIUsageLog:
    """Accumulates what a run spent, for the preflight and diagnostics panes."""

    calls: int = 0
    entries: list[dict[str, Any]] = field(default_factory=list)

    def record(self, purpose: str, usage: Usage) -> None:
        self.calls += 1
        self.entries.append({"purpose": purpose, **usage.as_dict()})

    @property
    def total_tokens(self) -> int:
        return sum(int(e.get("total_tokens") or 0) for e in self.entries)

    def as_dict(self) -> dict[str, Any]:
        return {"calls": self.calls, "total_tokens": self.total_tokens, "entries": self.entries}


def providers() -> list[LLMProvider]:
    return [cls() for cls in PROVIDER_ORDER]


def provider_table() -> list[dict[str, Any]]:
    return [provider.describe() for provider in providers()]


def available_providers() -> list[LLMProvider]:
    return [provider for provider in providers() if provider.available()]


def get_provider(name: str | None = None) -> LLMProvider | None:
    """Return a usable provider, or ``None`` when AI cannot run at all."""
    candidates = available_providers()
    if not candidates:
        return None
    if name:
        for provider in candidates:
            if provider.name == name:
                return provider
        return None
    return candidates[0]


def ai_enabled(mode: AIMode | str, deterministic_succeeded: bool) -> bool:
    """Decide whether an AI call is permitted right now."""
    mode = AIMode(mode) if not isinstance(mode, AIMode) else mode
    if mode is AIMode.DISABLED:
        return False
    if mode is AIMode.AUTO:
        return not deterministic_succeeded
    return True


# --------------------------------------------------------------------- features
def propose_schema(
    *,
    user_goal: str,
    page_content: str,
    provider_name: str | None = None,
    usage_log: AIUsageLog | None = None,
) -> ExtractionSchema | None:
    """Ask a model to name the columns visible in a sample (audit section C)."""
    provider = get_provider(provider_name)
    if provider is None:
        return None

    result = call_structured(
        provider,
        instruction=(
            "Propose the dataset columns a researcher could extract from this page. "
            "Use snake_case names. For each field copy one supporting value from the "
            "excerpt into 'evidence'. Propose nothing you cannot see."
        ),
        context=f"Researcher request: {user_goal[:500]}" if user_goal else "",
        schema=ProposedSchema,
        page_content=page_content,
    )
    if usage_log is not None and result.usage.provider:
        usage_log.record("propose_schema", result.usage)
    if not result.ok:
        return None

    proposal: ProposedSchema = result.value  # type: ignore[assignment]
    if not proposal.fields:
        return None

    # Reject a proposal whose evidence does not appear in the page.
    ratio = evidence_ratio([f.evidence for f in proposal.fields if f.evidence], page_content)
    if ratio < MIN_EVIDENCE_RATIO:
        return None

    return ExtractionSchema(
        name="ai_proposed",
        fields=[
            FieldSpec(
                name=field_.name,
                label=field_.name,
                dtype=field_.type,
                required=field_.required,
                name_source=NameSource.AI_INFERRED,
                confidence=Confidence.MEDIUM,
                sample=field_.evidence[:80] or None,
                notes="Proposed by AI from a page sample — review before use.",
            )
            for field_ in proposal.fields[:40]
        ],
    )


def map_fields(
    *,
    requested: list[str],
    columns: list[str],
    sample_rows: list[dict[str, Any]],
    provider_name: str | None = None,
    usage_log: AIUsageLog | None = None,
) -> dict[str, str] | None:
    """Semantic fallback for field mapping when deterministic matching fails."""
    provider = get_provider(provider_name)
    if provider is None or not requested or not columns:
        return None

    import json

    result = call_structured(
        provider,
        instruction=(
            "Map each requested research field to the column that holds it. "
            "Use null for a requested field that no column provides. "
            "Never map two requested fields to the same column unless it genuinely holds both."
        ),
        context=(
            f"Requested fields: {json.dumps(requested, ensure_ascii=False)}\n"
            f"Available columns: {json.dumps(columns, ensure_ascii=False)}\n"
            f"Sample rows: {json.dumps(sample_rows[:3], ensure_ascii=False, default=str)[:2000]}"
        ),
        schema=FieldMappingProposal,
    )
    if usage_log is not None and result.usage.provider:
        usage_log.record("map_fields", result.usage)
    if not result.ok:
        return None

    proposal: FieldMappingProposal = result.value  # type: ignore[assignment]
    mapping = {
        item.requested: item.column
        for item in proposal.mappings
        if item.column and item.column in columns
    }
    return mapping or None


def extract_records(
    *,
    instruction: str,
    page_content: str,
    columns: list[str] | None = None,
    provider_name: str | None = None,
    usage_log: AIUsageLog | None = None,
) -> list[dict[str, Any]] | None:
    """Last-resort semantic extraction, validated against page evidence."""
    provider = get_provider(provider_name)
    if provider is None:
        return None

    context = ""
    if columns:
        import json

        context = f"Use exactly these columns: {json.dumps(columns, ensure_ascii=False)}"

    result = call_structured(
        provider,
        instruction=(
            f"{instruction.strip()}\n"
            "Return one object per row. Copy values verbatim from the excerpt."
        ),
        context=context,
        schema=ExtractedRecords,
        page_content=page_content,
        max_tokens=3000,
    )
    if usage_log is not None and result.usage.provider:
        usage_log.record("extract_records", result.usage)
    if not result.ok:
        return None

    extracted: ExtractedRecords = result.value  # type: ignore[assignment]
    if not extracted.records:
        return None

    flat_values = [str(v) for row in extracted.records[:20] for v in row.values() if v is not None]
    if evidence_ratio(flat_values, page_content) < MIN_EVIDENCE_RATIO:
        return None
    return [dict(row) for row in extracted.records]


def review_extraction(
    *,
    columns: list[str],
    sample_rows: list[dict[str, Any]],
    user_goal: str = "",
    provider_name: str | None = None,
    usage_log: AIUsageLog | None = None,
) -> ValidationVerdict | None:
    """Optional sanity review of an extracted sample (audit section C)."""
    provider = get_provider(provider_name)
    if provider is None:
        return None

    import json

    result = call_structured(
        provider,
        instruction=(
            "Review this extracted sample for obvious problems: shifted columns, "
            "merged values, headers used as data, or values that do not match their column name."
        ),
        context=(
            f"Researcher request: {user_goal[:300]}\n"
            f"Columns: {json.dumps(columns, ensure_ascii=False)}\n"
            f"Rows: {json.dumps(sample_rows[:5], ensure_ascii=False, default=str)[:2500]}"
        ),
        schema=ValidationVerdict,
    )
    if usage_log is not None and result.usage.provider:
        usage_log.record("review_extraction", result.usage)
    return result.value if result.ok else None


def describe_variables(
    *,
    columns: list[str],
    sample_rows: list[dict[str, Any]],
    provider_name: str | None = None,
    usage_log: AIUsageLog | None = None,
) -> dict[str, dict[str, str]] | None:
    """Optional labels/units for the data dictionary (audit section V)."""
    provider = get_provider(provider_name)
    if provider is None:
        return None

    import json

    result = call_structured(
        provider,
        instruction=(
            "Write a short human label, a unit where one is evident, and a brief note "
            "for each variable. Leave a field empty rather than guessing."
        ),
        context=(
            f"Columns: {json.dumps(columns, ensure_ascii=False)}\n"
            f"Sample rows: {json.dumps(sample_rows[:3], ensure_ascii=False, default=str)[:2000]}"
        ),
        schema=DataDictionaryProposal,
    )
    if usage_log is not None and result.usage.provider:
        usage_log.record("describe_variables", result.usage)
    if not result.ok:
        return None

    proposal: DataDictionaryProposal = result.value  # type: ignore[assignment]
    return {
        item.variable: {"label": item.label, "unit": item.unit, "notes": item.notes}
        for item in proposal.variables
        if item.variable in columns
    }
