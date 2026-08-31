"""Google Gemini provider (optional).

The default model is overridable through ``SRWS_GOOGLE_MODEL``: gemini-2.0-flash
has been shut down, and pinning a model name in code turns a provider
deprecation into an application outage.
"""

from __future__ import annotations

import os

from .. import capabilities
from ..base import Completion, LLMProvider, Usage


class GoogleProvider(LLMProvider):
    name = "google"
    label = "Google Gemini"
    default_model = os.getenv("SRWS_GOOGLE_MODEL", "gemini-3.7-flash")
    credential = "google"
    package = "google.genai"
    install_hint = "pip install google-genai"
    docs = "https://ai.google.dev/gemini-api/docs"

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 1500,
        temperature: float | None = None,
    ) -> Completion:  # pragma: no cover - requires credentials
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
        chosen = model or self.default_model
        sampling = capabilities.for_model(chosen).sampling_kwargs(temperature)
        config = types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            system_instruction=system or None,
            **sampling,
        )
        response = client.models.generate_content(model=chosen, contents=prompt, config=config)
        meta = getattr(response, "usage_metadata", None)
        usage = Usage(
            input_tokens=getattr(meta, "prompt_token_count", None),
            output_tokens=getattr(meta, "candidates_token_count", None),
            model=chosen,
            provider=self.name,
        )
        return Completion(text=getattr(response, "text", "") or "", usage=usage)
