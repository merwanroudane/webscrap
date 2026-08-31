"""Optional external providers.

Importing this package never requires an optional dependency or a credential.
Each sub-module exposes ``providers()``, ``get_provider(name)`` and
``configured_provider()``; nothing is usable until the researcher configures it.
"""

from .base import (
    BaseProvider,
    ProviderCategory,
    ProviderDescriptor,
    ProviderState,
    ProviderStatus,
)

__all__ = [
    "BaseProvider",
    "ProviderCategory",
    "ProviderDescriptor",
    "ProviderState",
    "ProviderStatus",
]
