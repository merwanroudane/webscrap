"""OpenAI provider (optional)."""

from __future__ import annotations

import os

from .. import capabilities
from ..base import Completion, LLMProvider, Usage


class OpenAIProvider(LLMProvider):
    name = "openai"
    label = "OpenAI"
    default_model = os.getenv("SRWS_OPENAI_MODEL", "gpt-4o-mini")
    credential = "openai"
    package = "openai"
    install_hint = "pip install openai"
    docs = "https://platform.openai.com/docs/api-reference"

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 1500,
        temperature: float | None = None,
    ) -> Completion:  # pragma: no cover - requires credentials
        from openai import OpenAI

        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        chosen = model or self.default_model
        instructions = system or None
        sampling = capabilities.for_model(chosen).sampling_kwargs(temperature)
        response = client.responses.create(
            model=chosen,
            input=prompt,
            instructions=instructions,
            max_output_tokens=max_tokens,
            **sampling,
        )
        usage_obj = getattr(response, "usage", None)
        usage = Usage(
            input_tokens=getattr(usage_obj, "input_tokens", None),
            output_tokens=getattr(usage_obj, "output_tokens", None),
            model=chosen,
            provider=self.name,
        )
        return Completion(text=getattr(response, "output_text", "") or "", usage=usage)
