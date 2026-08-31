"""LiteLLM provider (optional).

LiteLLM routes to many backends behind one call, so it is offered as a single
optional provider rather than as a mandatory abstraction layer. The model
string carries the backend, e.g. ``anthropic/claude-sonnet-5``.
"""

from __future__ import annotations

import os

from .. import capabilities
from ..base import AIAvailability, Completion, LLMProvider, Usage

#: Any one of these being present is enough for LiteLLM to reach some backend.
_ANY_KEY = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY")


class LiteLLMProvider(LLMProvider):
    name = "litellm"
    label = "LiteLLM (multi-backend)"
    default_model = os.getenv("SRWS_LITELLM_MODEL", "gpt-4o-mini")
    package = "litellm"
    install_hint = "pip install litellm"
    docs = "https://docs.litellm.ai/docs/"

    def availability(self) -> AIAvailability:
        try:
            __import__("litellm")
        except Exception:
            return AIAvailability(
                False, "The optional package 'litellm' is not installed.", self.install_hint
            )
        if not any(os.getenv(key, "").strip() for key in _ANY_KEY):
            return AIAvailability(
                False,
                "No model provider key is configured for LiteLLM to route to.",
                "Set one of ANTHROPIC_API_KEY, OPENAI_API_KEY or GOOGLE_API_KEY.",
            )
        return AIAvailability(True)

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
