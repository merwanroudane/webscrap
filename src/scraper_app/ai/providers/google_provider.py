"""Google Gemini provider (optional)."""

from __future__ import annotations

import os

from ..base import Completion, LLMProvider, Usage


class GoogleProvider(LLMProvider):
    name = "google"
    label = "Google Gemini"
    default_model = "gemini-2.0-flash"
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
        temperature: float = 0.0,
    ) -> Completion:  # pragma: no cover - requires credentials
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
        chosen = model or self.default_model
        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            system_instruction=system or None,
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
