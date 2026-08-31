"""Provider-independent LLM contract (audit section C).

Rules this layer exists to enforce:

* the application runs with **zero** AI packages and **zero** API keys;
* an LLM is never called unless the researcher explicitly enabled AI;
* page content is untrusted data, sent bounded and wrapped, never with secrets;
* every response is validated against a Pydantic schema before it is used;
* usage/cost metadata is surfaced so the user can see what a run cost.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..config import has_credentials


class AIMode(str, Enum):
    """How willing the user is to involve a language model."""

    DISABLED = "disabled"
    AUTO = "auto"
    ALWAYS = "always"

    def label(self, lang: str = "en") -> str:
        en = {
            "disabled": "Disabled — never call a model",
            "auto": "Auto — only when deterministic extraction is insufficient",
            "always": "Always — allowed whenever it would help",
        }
        ar = {
            "disabled": "معطّل — لا يتم استدعاء أي نموذج",
            "auto": "تلقائي — فقط عندما لا يكفي الاستخراج الحتمي",
            "always": "دائمًا — مسموح كلما كان مفيدًا",
        }
        return (ar if lang == "ar" else en)[self.value]


@dataclass
class AIAvailability:
    ready: bool
    reason: str = ""
    install_hint: str = ""

    def __bool__(self) -> bool:  # pragma: no cover - trivial
        return self.ready


@dataclass
class Usage:
    """Token/cost metadata when the provider reports it."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    model: str = ""
    provider: str = ""

    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is None and self.output_tokens is None:
            return None
        return (self.input_tokens or 0) + (self.output_tokens or 0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class Completion:
    """One model response plus what it cost."""

    text: str
    usage: Usage = field(default_factory=Usage)
    raw: dict[str, Any] = field(default_factory=dict)


class LLMProvider(ABC):
    """Every AI backend implements exactly this."""

    name: str = "base"
    label: str = "Base provider"
    default_model: str = ""
    credential: str = ""
    package: str = ""
    install_hint: str = ""
    docs: str = ""
    cost_mode: str = "metered"

    #: Hard ceiling on how much untrusted page content may be sent at once.
    max_content_chars: int = 6000

    def availability(self) -> AIAvailability:
        if self.package:
            try:
                __import__(self.package)
            except Exception:
                return AIAvailability(
                    False,
                    f"The optional package '{self.package}' is not installed.",
                    self.install_hint or f"pip install {self.package}",
                )
        if self.credential and not has_credentials(self.credential):
            return AIAvailability(
                False,
                "API key not configured.",
                f"Set the {self.credential.upper()} key in your .env file.",
            )
        return AIAvailability(True)

    def available(self) -> bool:
        return bool(self.availability())

    @abstractmethod
    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 1500,
        temperature: float = 0.0,
    ) -> Completion:
        """Return one completion. Implementations must not retry indefinitely."""

    # ------------------------------------------------------------------ helpers
    def describe(self) -> dict[str, Any]:
        availability = self.availability()
        return {
            "provider": self.name,
            "label": self.label,
            "model": self.default_model,
            "ready": availability.ready,
            "reason": availability.reason,
            "install_hint": availability.install_hint,
            "cost_mode": self.cost_mode,
            "docs": self.docs,
        }
