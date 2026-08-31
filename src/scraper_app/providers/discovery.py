"""Source discovery providers (audit section P).

Discovery answers "which pages might hold this data?"; it never extracts. The
researcher always selects and approves a source before any extraction runs, and
a search result never triggers a crawl on its own.
"""

from __future__ import annotations

import os
from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from ..exceptions import ErrorCode, ScraperError
from ..security.url_guard import is_allowed
from .base import BaseProvider, ProviderCategory, ProviderDescriptor

_TIMEOUT = 30.0


@dataclass
class SourceCandidate:
    """One discovered source, shown as a card for the researcher to approve."""

    url: str
    title: str = ""
    snippet: str = ""
    score: float | None = None
    published: str = ""
    provider: str = ""

    @property
    def domain(self) -> str:
        return urlsplit(self.url).netloc.lower()

    def as_row(self) -> dict[str, Any]:
        return {
            "title": self.title or self.domain,
            "domain": self.domain,
            "url": self.url,
            "snippet": self.snippet[:300],
            "published": self.published,
            "relevance": round(self.score, 3) if isinstance(self.score, (int, float)) else "",
            "found_by": self.provider,
        }


@dataclass
class DiscoveryQuery:
    query: str
    max_results: int = 10
    include_domains: list[str] = field(default_factory=list)


class SourceDiscoveryProvider(BaseProvider):
    """Search the web for candidate data sources."""

    @abstractmethod
    def search(self, query: DiscoveryQuery) -> list[SourceCandidate]: ...

    def describe(self) -> dict[str, Any]:
        return self.descriptor.as_row()

    def _post(
        self, url: str, *, headers: dict[str, str], json_body: dict[str, Any]
    ) -> dict[str, Any]:
        import httpx

        self._require_ready()
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                response = client.post(url, headers=headers, json=json_body)
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
        try:
            return response.json()
        except Exception as exc:
            raise ScraperError(
                ErrorCode.CONTENT_UNSUPPORTED, f"{self.label} returned a non-JSON response."
            ) from exc

    @staticmethod
    def _keep(candidates: list[SourceCandidate]) -> list[SourceCandidate]:
        """Drop anything the URL guard would refuse anyway."""
        seen: set[str] = set()
        kept: list[SourceCandidate] = []
        for candidate in candidates:
            if not candidate.url or candidate.url in seen:
                continue
            if not is_allowed(candidate.url):
                continue
            seen.add(candidate.url)
            kept.append(candidate)
        return kept


class TavilyProvider(SourceDiscoveryProvider):
    """https://docs.tavily.com — POST /search with a bearer key."""

    descriptor = ProviderDescriptor(
        id="tavily",
        label="Tavily",
        category=ProviderCategory.DISCOVERY,
        cost_mode="metered",
        env_keys=("TAVILY_API_KEY",),
        docs="https://docs.tavily.com/documentation/api-reference/endpoint/search",
        privacy_note="Your search text is sent to Tavily. Page content is not.",
        capabilities=("search",),
    )

    def search(self, query: DiscoveryQuery) -> list[SourceCandidate]:
        body: dict[str, Any] = {
            "query": query.query,
            "max_results": max(1, min(query.max_results, 20)),
            "search_depth": "basic",
        }
        if query.include_domains:
            body["include_domains"] = query.include_domains[:300]

        payload = self._post(
            "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {os.environ['TAVILY_API_KEY']}"},
            json_body=body,
        )
        return self._keep(
            [
                SourceCandidate(
                    url=str(item.get("url", "")),
                    title=str(item.get("title", "")),
                    snippet=str(item.get("content", "")),
                    score=item.get("score"),
                    provider="tavily",
                )
                for item in payload.get("results", [])
            ]
        )


class ExaProvider(SourceDiscoveryProvider):
    """https://exa.ai/docs — POST /search with an ``x-api-key`` header."""

    descriptor = ProviderDescriptor(
        id="exa",
        label="Exa",
        category=ProviderCategory.DISCOVERY,
        cost_mode="metered",
        env_keys=("EXA_API_KEY",),
        docs="https://exa.ai/docs/reference/search",
        privacy_note="Your search text is sent to Exa. Page content is not.",
        capabilities=("search",),
    )

    def search(self, query: DiscoveryQuery) -> list[SourceCandidate]:
        body: dict[str, Any] = {
            "query": query.query,
            "numResults": max(1, min(query.max_results, 100)),
            "type": "auto",
        }
        if query.include_domains:
            body["includeDomains"] = query.include_domains

        payload = self._post(
            "https://api.exa.ai/search",
            headers={"x-api-key": os.environ["EXA_API_KEY"], "Content-Type": "application/json"},
            json_body=body,
        )
        return self._keep(
            [
                SourceCandidate(
                    url=str(item.get("url", "")),
                    title=str(item.get("title", "")),
                    snippet=str(item.get("text", ""))[:400],
                    published=str(item.get("publishedDate", "")),
                    provider="exa",
                )
                for item in payload.get("results", [])
            ]
        )


class JinaSearchProvider(SourceDiscoveryProvider):
    """https://jina.ai/reader — s.jina.ai returns search results as JSON."""

    descriptor = ProviderDescriptor(
        id="jina_search",
        label="Jina Search",
        category=ProviderCategory.DISCOVERY,
        cost_mode="metered",
        env_keys=("JINA_API_KEY",),
        docs="https://jina.ai/reader/",
        privacy_note="Your search text is sent to Jina.",
        capabilities=("search",),
    )

    def search(self, query: DiscoveryQuery) -> list[SourceCandidate]:
        import httpx

        self._require_ready()
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                response = client.get(
                    "https://s.jina.ai/",
                    params={"q": query.query},
                    headers={
                        "Authorization": f"Bearer {os.environ['JINA_API_KEY']}",
                        "Accept": "application/json",
                    },
                )
        except httpx.HTTPError as exc:
            raise ScraperError(
                ErrorCode.CONNECTION_ERROR,
                f"Jina Search could not be reached ({exc.__class__.__name__}).",
            ) from exc
        if response.status_code >= 400:
            raise ScraperError(
                ErrorCode.HTTP_ERROR, f"Jina Search returned {response.status_code}."
            )

        try:
            payload = response.json()
        except Exception as exc:
            raise ScraperError(
                ErrorCode.CONTENT_UNSUPPORTED, "Jina Search returned a non-JSON response."
            ) from exc

        items = payload.get("data") if isinstance(payload, dict) else payload
        return self._keep(
            [
                SourceCandidate(
                    url=str(item.get("url", "")),
                    title=str(item.get("title", "")),
                    snippet=str(item.get("description", "") or item.get("content", ""))[:400],
                    provider="jina_search",
                )
                for item in (items or [])[: query.max_results]
                if isinstance(item, dict)
            ]
        )


PROVIDERS: dict[str, type[SourceDiscoveryProvider]] = {
    "tavily": TavilyProvider,
    "exa": ExaProvider,
    "jina_search": JinaSearchProvider,
}


def providers() -> list[SourceDiscoveryProvider]:
    return [cls() for cls in PROVIDERS.values()]


def get_provider(name: str) -> SourceDiscoveryProvider | None:
    cls = PROVIDERS.get(name)
    return cls() if cls else None


def configured_provider(preferred: str | None = None) -> SourceDiscoveryProvider | None:
    if preferred:
        provider = get_provider(preferred)
        return provider if provider and provider.available() else None
    for provider in providers():
        if provider.available():
            return provider
    return None


def any_configured() -> bool:
    return configured_provider() is not None
