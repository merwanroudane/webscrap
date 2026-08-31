"""Secret hygiene helpers (spec sections 40, 65).

Nothing here stores credentials. These helpers exist so that logs, recipes,
provenance files and generated code can never carry an Authorization header,
API key, cookie jar or token.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

SENSITIVE_HEADER_NAMES = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "api-key",
    "apikey",
    "x-auth-token",
    "authentication",
    "x-csrf-token",
    "x-access-token",
}

SENSITIVE_PARAM_NAMES = {
    "api_key",
    "apikey",
    "key",
    "token",
    "access_token",
    "auth",
    "password",
    "secret",
    "signature",
    "sig",
}

_REDACTED = "***redacted***"
_TOKEN_PATTERN = re.compile(
    r"(?i)\b(sk-[A-Za-z0-9_\-]{12,}|ghp_[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._\-]{12,})"
)


def redact_headers(headers: dict[str, str] | None) -> dict[str, str]:
    """Return headers with credential-bearing values replaced."""
    if not headers:
        return {}
    return {
        k: (_REDACTED if k.lower() in SENSITIVE_HEADER_NAMES else v) for k, v in headers.items()
    }


def redact_params(params: dict[str, Any] | None) -> dict[str, Any]:
    if not params:
        return {}
    return {
        k: (_REDACTED if k.lower() in SENSITIVE_PARAM_NAMES else v) for k, v in params.items()
    }


def sanitize_url(url: str) -> str:
    """Strip userinfo and redact obviously secret query parameters."""
    if not url:
        return ""
    parts = urlsplit(url)
    netloc = parts.hostname or ""
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    query = parts.query
    if query:
        pairs = []
        for chunk in query.split("&"):
            if "=" in chunk:
                name, _, _value = chunk.partition("=")
                if name.lower() in SENSITIVE_PARAM_NAMES:
                    pairs.append(f"{name}={_REDACTED}")
                    continue
            pairs.append(chunk)
        query = "&".join(pairs)
    return urlunsplit((parts.scheme, netloc, parts.path, query, ""))


def sanitize_text(text: str) -> str:
    """Redact token-shaped substrings from free text before it reaches a log."""
    if not text:
        return ""
    return _TOKEN_PATTERN.sub(_REDACTED, text)


def strip_secrets(payload: dict[str, Any]) -> dict[str, Any]:
    """Deep-copy a mapping with header/param/secret values removed.

    Used before writing a recipe or provenance file so that credentials the
    researcher typed in Advanced mode are never persisted.
    """
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = key.lower()
        if lowered in {"headers"}:
            cleaned[key] = redact_headers(value if isinstance(value, dict) else {})
        elif lowered in {"cookies"}:
            cleaned[key] = {} if isinstance(value, dict) else value
        elif lowered in {"params", "query_params"}:
            cleaned[key] = redact_params(value if isinstance(value, dict) else {})
        elif lowered in SENSITIVE_PARAM_NAMES or lowered in SENSITIVE_HEADER_NAMES:
            cleaned[key] = _REDACTED
        elif isinstance(value, dict):
            cleaned[key] = strip_secrets(value)
        elif isinstance(value, list):
            cleaned[key] = [strip_secrets(v) if isinstance(v, dict) else v for v in value]
        elif isinstance(value, str):
            cleaned[key] = sanitize_text(value)
        else:
            cleaned[key] = value
    return cleaned
