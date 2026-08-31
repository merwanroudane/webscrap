"""Shared contract for every external provider (audit sections AL and AQ).

One descriptor type describes remote browsers, managed fetch services, source
discovery, semantic content APIs and document extractors alike, so the Settings
page can render them all honestly from a single table.

Status vocabulary, from the audit:

``ready``           usable right now
``optional``        real adapter, package missing
``not_configured``  real adapter, package present, credentials missing
``catalogue``       known provider, adapter not implemented here
``blocked``         cannot be implemented, with a documented reason
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProviderStatus(str, Enum):
    READY = "ready"
    OPTIONAL = "optional"
    NOT_CONFIGURED = "not_configured"
    CATALOGUE = "catalogue"
    BLOCKED = "blocked"

    def label(self, lang: str = "en") -> str:
        en = {
            "ready": "Ready",
            "optional": "Not installed",
            "not_configured": "Not configured",
            "catalogue": "Catalogue",
            "blocked": "Blocked",
        }
        ar = {
            "ready": "جاهز",
            "optional": "غير مثبت",
            "not_configured": "غير مضبوط",
            "catalogue": "كتالوج",
            "blocked": "محجوب",
        }
        return (ar if lang == "ar" else en)[self.value]

    def symbol(self) -> str:
        return {
            "ready": "✓",
            "optional": "○",
            "not_configured": "◍",
            "catalogue": "–",
            "blocked": "✕",
        }[self.value]

    def tone(self) -> str:
        return {
            "ready": "ok",
            "optional": "warn",
            "not_configured": "warn",
            "catalogue": "neutral",
            "blocked": "err",
        }[self.value]


class ProviderCategory(str, Enum):
    REMOTE_BROWSER = "remote_browser"
    MANAGED_FETCH = "managed_fetch"
    DISCOVERY = "discovery"
    SEMANTIC_CONTENT = "semantic_content"
    DOCUMENT = "document"
    LLM = "llm"
    ENGINE = "engine"


@dataclass
class ProviderState:
    status: ProviderStatus
    detail: str = ""
    install_hint: str = ""

    @property
    def ready(self) -> bool:
        return self.status is ProviderStatus.READY


@dataclass
class ProviderDescriptor:
    """Everything the Settings page needs about one provider."""

    id: str
    label: str
    category: ProviderCategory
    cost_mode: str = "metered"  # free | local_compute | metered
    local: bool = False
    package: str | None = None
    env_keys: tuple[str, ...] = ()
    install_hint: str = ""
    docs: str = ""
    privacy_note: str = ""
    capabilities: tuple[str, ...] = ()
    implemented: bool = True
    blocked_reason: str = ""
    notes: str = ""

    def credentials_present(self) -> bool:
        return all(os.getenv(key, "").strip() for key in self.env_keys) if self.env_keys else True

    def package_present(self) -> bool:
        if not self.package:
            return True
        try:
            __import__(self.package)
            return True
        except Exception:
            return False

    def state(self) -> ProviderState:
        if not self.implemented:
            return ProviderState(
                ProviderStatus.BLOCKED if self.blocked_reason else ProviderStatus.CATALOGUE,
                self.blocked_reason or "Known provider — adapter not implemented in this version.",
            )
        if not self.package_present():
            return ProviderState(
                ProviderStatus.OPTIONAL,
                f"The optional package '{self.package}' is not installed.",
                self.install_hint or (f"pip install {self.package}" if self.package else ""),
            )
        if not self.credentials_present():
            missing = [k for k in self.env_keys if not os.getenv(k, "").strip()]
            return ProviderState(
                ProviderStatus.NOT_CONFIGURED,
                "Missing credentials: " + ", ".join(missing),
                f"Set {' and '.join(missing)} in your .env file.",
            )
        return ProviderState(ProviderStatus.READY, "Available now.")

    def as_row(self) -> dict[str, Any]:
        state = self.state()
        return {
            "id": self.id,
            "provider": self.label,
            "category": self.category.value,
            "status": f"{state.status.symbol()} {state.status.label()}",
            "detail": state.detail,
            "cost": self.cost_mode,
            "where": "local" if self.local else "cloud",
            "setup": state.install_hint
            or (", ".join(self.env_keys) if self.env_keys else "built-in"),
            "docs": self.docs,
        }


class BaseProvider(ABC):
    """Common behaviour for all provider adapters."""

    descriptor: ProviderDescriptor

    def state(self) -> ProviderState:
        return self.descriptor.state()

    def available(self) -> bool:
        return self.state().ready

    @property
    def id(self) -> str:
        return self.descriptor.id

    @property
    def label(self) -> str:
        return self.descriptor.label

    def _require_ready(self) -> None:
        from ..exceptions import ErrorCode, ScraperError

        state = self.state()
        if state.ready:
            return
        code = {
            ProviderStatus.OPTIONAL: ErrorCode.OPTIONAL_ENGINE_NOT_INSTALLED,
            ProviderStatus.NOT_CONFIGURED: ErrorCode.API_KEY_MISSING,
            ProviderStatus.CATALOGUE: ErrorCode.OPTIONAL_ENGINE_NOT_INSTALLED,
            ProviderStatus.BLOCKED: ErrorCode.OPTIONAL_ENGINE_NOT_INSTALLED,
        }[state.status]
        raise ScraperError(code, state.detail, {"install_hint": state.install_hint})

    @abstractmethod
    def describe(self) -> dict[str, Any]:
        """Return a row for the Settings table."""


@dataclass
class ProviderRegistryEntry:
    descriptor: ProviderDescriptor
    factory: Any = None
    instance: BaseProvider | None = field(default=None, repr=False)


def env_first(*names: str) -> str:
    """Return the first non-empty environment variable among ``names``."""
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""
