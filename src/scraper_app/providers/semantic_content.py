"""Semantic content providers (audit section O).

These turn one page into clean article text or a structured object. They are
for prose-heavy pages; ordinary tabular datasets are never routed through them,
because a deterministic parser does that job better and free.
"""

from __future__ import annotations

import os
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from ..exceptions import ErrorCode, ScraperError
from ..security.url_guard import guard_url
from .base import BaseProvider, ProviderCategory, ProviderDescriptor

_TIMEOUT = 45.0


@dataclass
class SemanticDocument:
    """Normalized result: one document with text plus whatever metadata exists."""

    url: str
    title: str = ""
    text: str = ""
    author: str = ""
    published: str = ""
    provider: str = ""
    fields: dict[str, Any] = field(default_factory=dict)

    def as_record(self) -> dict[str, Any]:
        record = {
            "url": self.url,
            "title": self.title,
            "author": self.author,
            "date": self.published,
            "text": self.text,
            "text_chars": len(self.text),
        }
        record.update({k: v for k, v in self.fields.items() if k not in record})
        return record


class SemanticContentProvider(BaseProvider):
    @abstractmethod
    def read(self, url: str) -> SemanticDocument: ...

    def describe(self) -> dict[str, Any]:
        return self.descriptor.as_row()

    def _get(
        self, url: str, *, headers: dict[str, str], params: dict[str, Any] | None = None
    ) -> Any:
        import httpx

        self._require_ready()
        try:
            with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
                response = client.get(url, headers=headers, params=params)
        except httpx.HTTPError as exc:
            raise ScraperError(
                ErrorCode.CONNECTION_ERROR,
                f"{self.label} could not be reached ({exc.__class__.__name__}).",
            ) from exc
        if response.status_code in {401, 403}:
            raise ScraperError(ErrorCode.API_AUTH_REQUIRED, f"{self.label} rejected the API key.")
        if response.status_code >= 400:
            raise ScraperError(
                ErrorCode.HTTP_ERROR, f"{self.label} returned {response.status_code}."
            )
        if "json" in (response.headers.get("content-type") or "").lower():
            try:
                return response.json()
            except Exception:
                return response.text
        return response.text


class DiffbotProvider(SemanticContentProvider):
    """https://docs.diffbot.com — Analyze API returns a typed object per page."""

    descriptor = ProviderDescriptor(
        id="diffbot",
        label="Diffbot",
        category=ProviderCategory.SEMANTIC_CONTENT,
        cost_mode="metered",
        env_keys=("DIFFBOT_TOKEN",),
        docs="https://docs.diffbot.com/reference/analyze",
        privacy_note="The target URL is sent to Diffbot, which fetches the page itself.",
        capabilities=("semantic_extraction", "hosted"),
    )

    def read(self, url: str) -> SemanticDocument:
        guarded = guard_url(url)
        payload = self._get(
            "https://api.diffbot.com/v3/analyze",
            headers={"Accept": "application/json"},
            params={"token": os.environ["DIFFBOT_TOKEN"], "url": guarded.url},
        )
        if not isinstance(payload, dict):
            raise ScraperError(
                ErrorCode.CONTENT_UNSUPPORTED, "Diffbot returned an unexpected response."
            )
        objects = payload.get("objects") or []
        if not objects:
            raise ScraperError(ErrorCode.NO_DATA_DETECTED, "Diffbot found no content on that page.")
        obj = objects[0]
        return SemanticDocument(
            url=str(obj.get("pageUrl") or guarded.url),
            title=str(obj.get("title", "")),
            text=str(obj.get("text", "")),
            author=str(obj.get("author", "")),
            published=str(obj.get("date", "")),
            provider="diffbot",
            fields={
                "type": obj.get("type", ""),
                "site_name": obj.get("siteName", ""),
                "language": obj.get("humanLanguage", ""),
            },
        )


class JinaReaderProvider(SemanticContentProvider):
    """https://jina.ai/reader — r.jina.ai returns clean markdown for a page."""

    descriptor = ProviderDescriptor(
        id="jina_reader",
        label="Jina Reader",
        category=ProviderCategory.SEMANTIC_CONTENT,
        cost_mode="metered",
        env_keys=("JINA_API_KEY",),
        docs="https://jina.ai/reader/",
        privacy_note="The target URL is sent to Jina, which fetches the page itself.",
        capabilities=("semantic_extraction", "hosted"),
        notes="Works without a key at a lower rate limit, but a key is required here for predictability.",
    )

    def read(self, url: str) -> SemanticDocument:
        guarded = guard_url(url)
        payload = self._get(
            f"https://r.jina.ai/{quote(guarded.url, safe=':/?&=%')}",
            headers={
                "Authorization": f"Bearer {os.environ['JINA_API_KEY']}",
                "Accept": "application/json",
                "X-Return-Format": "markdown",
            },
        )
        if isinstance(payload, dict):
            data = payload.get("data", payload)
            return SemanticDocument(
                url=str(data.get("url", guarded.url)),
                title=str(data.get("title", "")),
                text=str(data.get("content", "")),
                published=str(data.get("publishedTime", "")),
                provider="jina_reader",
            )
        text = str(payload or "")
        if not text.strip():
            raise ScraperError(
                ErrorCode.NO_DATA_DETECTED, "Jina Reader returned an empty document."
            )
        return SemanticDocument(url=guarded.url, text=text, provider="jina_reader")


PROVIDERS: dict[str, type[SemanticContentProvider]] = {
    "diffbot": DiffbotProvider,
    "jina_reader": JinaReaderProvider,
}


def providers() -> list[SemanticContentProvider]:
    return [cls() for cls in PROVIDERS.values()]


def get_provider(name: str) -> SemanticContentProvider | None:
    cls = PROVIDERS.get(name)
    return cls() if cls else None


def configured_provider(preferred: str | None = None) -> SemanticContentProvider | None:
    if preferred:
        provider = get_provider(preferred)
        return provider if provider and provider.available() else None
    for provider in providers():
        if provider.available():
            return provider
    return None
