"""One table of every provider in the application (audit section AL).

The Settings page renders this. It must always tell the truth: a provider is
only ``Ready`` when a real adapter exists, its package imports and its
credentials are present.
"""

from __future__ import annotations

from typing import Any

from ..ai import service as ai_service
from . import discovery, documents, managed_fetch, remote_browser, semantic_content
from .base import ProviderCategory, ProviderDescriptor, ProviderState, ProviderStatus

CATEGORY_LABEL = {
    ProviderCategory.LLM: "AI model",
    ProviderCategory.REMOTE_BROWSER: "Remote browser",
    ProviderCategory.MANAGED_FETCH: "Managed fetch",
    ProviderCategory.DISCOVERY: "Source discovery",
    ProviderCategory.SEMANTIC_CONTENT: "Semantic content",
    ProviderCategory.DOCUMENT: "Document",
    ProviderCategory.ENGINE: "Extraction engine",
}


def _litellm_state() -> ProviderState:
    """Mirror the LiteLLM provider's own availability check, so they agree."""
    from ..ai.providers.litellm_provider import LiteLLMProvider

    availability = LiteLLMProvider().availability()
    if availability.ready:
        return ProviderState(ProviderStatus.READY, "Available now.")
    return ProviderState(
        ProviderStatus.NOT_CONFIGURED,
        availability.reason,
        getattr(availability, "install_hint", "") or "",
    )


#: AI providers are described by the ai package; mirror them as descriptors so
#: the Settings table can show every external dependency in one place.
_AI_DESCRIPTORS = {
    "anthropic": ProviderDescriptor(
        id="anthropic",
        label="Anthropic Claude",
        category=ProviderCategory.LLM,
        cost_mode="metered",
        package="anthropic",
        env_keys=("ANTHROPIC_API_KEY",),
        install_hint="pip install anthropic",
        docs="https://docs.anthropic.com/en/api/getting-started",
        privacy_note="Bounded page excerpts are sent to Anthropic when AI is enabled.",
    ),
    "openai": ProviderDescriptor(
        id="openai",
        label="OpenAI",
        category=ProviderCategory.LLM,
        cost_mode="metered",
        package="openai",
        env_keys=("OPENAI_API_KEY",),
        install_hint="pip install openai",
        docs="https://platform.openai.com/docs/api-reference",
        privacy_note="Bounded page excerpts are sent to OpenAI when AI is enabled.",
    ),
    "google": ProviderDescriptor(
        id="google",
        label="Google Gemini",
        category=ProviderCategory.LLM,
        cost_mode="metered",
        package="google.genai",
        env_keys=("GOOGLE_API_KEY",),
        install_hint="pip install google-genai",
        docs="https://ai.google.dev/gemini-api/docs",
        privacy_note="Bounded page excerpts are sent to Google when AI is enabled.",
    ),
    "litellm": ProviderDescriptor(
        id="litellm",
        label="LiteLLM (multi-backend)",
        category=ProviderCategory.LLM,
        cost_mode="metered",
        package="litellm",
        install_hint="pip install litellm",
        docs="https://docs.litellm.ai/docs/",
        privacy_note="Routes to whichever backend you configure.",
        notes="Needs the key for the backend its model resolves to.",
        # LiteLLM needs one of several keys, and which one depends on the model
        # it resolves to. Asking the provider itself is the only way this table
        # and the AI page can agree (audit v0.2 section 27).
        state_resolver=_litellm_state,
    ),
}


def all_descriptors() -> list[ProviderDescriptor]:
    """Every non-engine provider descriptor known to the application."""
    descriptors: list[ProviderDescriptor] = list(_AI_DESCRIPTORS.values())
    for module in (remote_browser, managed_fetch, discovery, semantic_content, documents):
        descriptors.extend(provider.descriptor for provider in module.providers())
    return descriptors


def provider_rows() -> list[dict[str, Any]]:
    """Rows for the Settings table, readiest first then alphabetical."""
    order = {
        ProviderStatus.READY: 0,
        ProviderStatus.NOT_CONFIGURED: 1,
        ProviderStatus.OPTIONAL: 2,
        ProviderStatus.CATALOGUE: 3,
        ProviderStatus.BLOCKED: 4,
    }
    rows = []
    for descriptor in all_descriptors():
        row = descriptor.as_row()
        row["category"] = CATEGORY_LABEL.get(descriptor.category, descriptor.category.value)
        row["_order"] = (order.get(descriptor.state().status, 5), descriptor.label.lower())
        rows.append(row)
    rows.sort(key=lambda r: r.pop("_order"))
    return rows


def summary() -> dict[str, int]:
    """Counts per status, for the badges above the table."""
    counts: dict[str, int] = {}
    for descriptor in all_descriptors():
        status = descriptor.state().status.value
        counts[status] = counts.get(status, 0) + 1
    return counts


def configured_summary() -> dict[str, Any]:
    """What is actually usable right now, for the preflight and diagnostics."""
    return {
        "ai_provider": (ai_service.get_provider().name if ai_service.get_provider() else None),
        "remote_browser": (
            remote_browser.configured_provider().id
            if remote_browser.configured_provider()
            else None
        ),
        "managed_fetch": (
            managed_fetch.configured_provider().id if managed_fetch.configured_provider() else None
        ),
        "discovery": (
            discovery.configured_provider().id if discovery.configured_provider() else None
        ),
        "semantic_content": (
            semantic_content.configured_provider().id
            if semantic_content.configured_provider()
            else None
        ),
        "document_extractor": (
            documents.best_extractor().id if documents.best_extractor() else None
        ),
    }
