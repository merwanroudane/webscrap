"""What a given model actually accepts (audit v0.2 sections 7 and 8).

Not every model takes the same request. Claude Sonnet 5 returns a 400 error if
``temperature``, ``top_p`` or ``top_k`` is set to a non-default value, while
most other models accept them. A provider abstraction that assumes one shared
parameter set will therefore fail on its own default model.

Capabilities are matched by model-name prefix and can be overridden per
provider, so a new model does not require a code change to become usable — set
the model through its environment variable and the safe default applies.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelCapabilities:
    """Which optional request parameters a model tolerates."""

    supports_temperature: bool = True
    supports_top_p: bool = True
    supports_system_prompt: bool = True
    #: Newer Anthropic models steer depth with `effort` instead of sampling.
    supports_effort: bool = False

    def sampling_kwargs(self, temperature: float | None) -> dict[str, float]:
        """Return the sampling arguments this model will accept."""
        if temperature is None or not self.supports_temperature:
            return {}
        return {"temperature": temperature}


#: Model families that reject sampling parameters. Prefix match, longest first.
#: Source: platform.claude.com/docs/en/models/sonnet-5/overview — "Setting
#: temperature, top_p, or top_k to non-default values returns a 400 error."
_NO_SAMPLING_PREFIXES = (
    "claude-fable-5",
    "claude-opus-5",
    "claude-sonnet-5",
)

_EFFORT_PREFIXES = (
    "claude-fable-5",
    "claude-opus-5",
    "claude-sonnet-5",
)


def for_model(model: str) -> ModelCapabilities:
    """Return the capabilities of ``model``, defaulting to permissive."""
    name = (model or "").strip().lower()
    no_sampling = any(name.startswith(prefix) for prefix in _NO_SAMPLING_PREFIXES)
    return ModelCapabilities(
        supports_temperature=not no_sampling,
        supports_top_p=not no_sampling,
        supports_effort=any(name.startswith(prefix) for prefix in _EFFORT_PREFIXES),
    )
