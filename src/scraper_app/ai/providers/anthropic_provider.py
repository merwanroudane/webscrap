"""Anthropic provider (optional)."""

from __future__ import annotations

import os

from ..base import Completion, LLMProvider, Usage


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    label = "Anthropic Claude"
    default_model = "claude-sonnet-5"
    credential = "anthropic"
    package = "anthropic"
    install_hint = "pip install anthropic"
    docs = "https://docs.anthropic.com/en/api/getting-started"

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 1500,
        temperature: float = 0.0,
    ) -> Completion:  # pragma: no cover - requires credentials
        import anthropic

        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        chosen = model or self.default_model
        message = client.messages.create(
            model=chosen,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in message.content if hasattr(block, "text"))
        usage = Usage(
            input_tokens=getattr(message.usage, "input_tokens", None),
            output_tokens=getattr(message.usage, "output_tokens", None),
            model=chosen,
            provider=self.name,
        )
        return Completion(text=text, usage=usage)
