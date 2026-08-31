"""LiteLLM provider (optional).

LiteLLM routes to many backends behind one call, so it is offered as a single
optional provider rather than as a mandatory abstraction layer. The model
string carries the backend, e.g. ``anthropic/claude-sonnet-5``.

Audit v0.2 section 26 recorded a real bug here: availability was true when
*any* backend key was present, but the default model was always ``gpt-4o-mini``.
A user with only ``ANTHROPIC_API_KEY`` was therefore told "Ready" and then got
an authentication failure on the first call.

The fix is that one function decides both answers. :func:`resolve_model` picks a
model that matches a key the user actually has, and ``availability`` reports
ready only when the key that *that* model needs is present.
"""

from __future__ import annotations

import os

from .. import capabilities
from ..base import AIAvailability, Completion, LLMProvider, Usage

#: Backend prefix -> the environment variables LiteLLM reads for it. A model
#: string with no prefix is OpenAI, which is LiteLLM's own default.
BACKEND_KEYS: dict[str, tuple[str, ...]] = {
    "": ("OPENAI_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "azure": ("AZURE_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "vertex_ai": ("GOOGLE_API_KEY",),
    "mistral": ("MISTRAL_API_KEY",),
    "groq": ("GROQ_API_KEY",),
    "cohere": ("COHERE_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "deepseek": ("DEEPSEEK_API_KEY",),
}

#: Preference order for choosing a default. Each entry is (key, model). The
#: first entry whose key is set wins, so the default always matches a backend
#: the user can actually reach.
_DEFAULT_CHOICES: tuple[tuple[str, str], ...] = (
    ("OPENAI_API_KEY", "gpt-4o-mini"),
    ("ANTHROPIC_API_KEY", "anthropic/claude-sonnet-5"),
    ("GEMINI_API_KEY", "gemini/gemini-3.7-flash"),
    ("GOOGLE_API_KEY", "gemini/gemini-3.7-flash"),
)

#: Used only when nothing is configured, so the label has something to show.
FALLBACK_MODEL = "gpt-4o-mini"


def backend_of(model: str) -> str:
    """The LiteLLM backend prefix of a model string ("" means OpenAI)."""
    text = (model or "").strip()
    prefix, separator, _rest = text.partition("/")
    return prefix.lower() if separator else ""


def keys_for_model(model: str) -> tuple[str, ...]:
    """Which environment variables that model needs. Empty means unknown."""
    return BACKEND_KEYS.get(backend_of(model), ())


def resolve_model() -> str:
    """The model this provider will use, given the current environment.

    ``SRWS_LITELLM_MODEL`` always wins — an explicit choice is never
    second-guessed, even when its key is missing, because reporting *that*
    honestly is more useful than silently substituting another backend.
    """
    override = os.getenv("SRWS_LITELLM_MODEL", "").strip()
    if override:
        return override
    for key, model in _DEFAULT_CHOICES:
        if os.getenv(key, "").strip():
            return model
    return FALLBACK_MODEL


class LiteLLMProvider(LLMProvider):
    name = "litellm"
    label = "LiteLLM (multi-backend)"
    package = "litellm"
    install_hint = "pip install litellm"
    docs = "https://docs.litellm.ai/docs/"

    @property
    def default_model(self) -> str:  # type: ignore[override]
        return resolve_model()

    def availability(self) -> AIAvailability:
        try:
            __import__("litellm")
        except Exception:
            return AIAvailability(
                False, "The optional package 'litellm' is not installed.", self.install_hint
            )

        model = resolve_model()
        needed = keys_for_model(model)
        if not needed:
            # An unrecognised backend: we cannot prove it is misconfigured, so
            # let the call through rather than blocking a valid setup.
            return AIAvailability(True)
        if any(os.getenv(key, "").strip() for key in needed):
            return AIAvailability(True)

        return AIAvailability(
            False,
            f"LiteLLM is set to '{model}', but no key for that backend is configured.",
            f"Set {' or '.join(needed)}, or choose another model with SRWS_LITELLM_MODEL.",
        )

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 1500,
        temperature: float | None = None,
    ) -> Completion:  # pragma: no cover - requires credentials
        import litellm

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        chosen = model or self.default_model
        sampling = capabilities.for_model(chosen).sampling_kwargs(temperature)
        response = litellm.completion(
            model=chosen,
            messages=messages,
            max_tokens=max_tokens,
            **sampling,
        )
        text = response["choices"][0]["message"]["content"] or ""
        usage_obj = response.get("usage") or {}
        usage = Usage(
            input_tokens=usage_obj.get("prompt_tokens"),
            output_tokens=usage_obj.get("completion_tokens"),
            model=chosen,
            provider=self.name,
        )
        return Completion(text=text, usage=usage)
