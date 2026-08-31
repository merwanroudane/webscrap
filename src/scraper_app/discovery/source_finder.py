"""Find sources workflow (audit section P).

Discovery is deliberately separate from extraction:

    research question → candidate sources → the researcher approves one
    → Analyze Website → extraction

A search result never starts a crawl by itself. Every candidate passes the URL
guard before it is offered, and the researcher must click through to analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..logging_config import RunLogger
from ..providers import discovery as discovery_providers
from ..providers.discovery import DiscoveryQuery, SourceCandidate


@dataclass
class DiscoveryOutcome:
    query: str
    provider: str
    candidates: list[SourceCandidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def rows(self) -> list[dict[str, Any]]:
        return [candidate.as_row() for candidate in self.candidates]


def available_providers() -> list[dict[str, Any]]:
    """Discovery providers and their configuration state."""
    return [provider.describe() for provider in discovery_providers.providers()]


def any_available() -> bool:
    return discovery_providers.configured_provider() is not None


def find_sources(
    query: str,
    *,
    provider_name: str | None = None,
    max_results: int = 10,
    include_domains: list[str] | None = None,
    logger: RunLogger | None = None,
) -> DiscoveryOutcome:
    """Search for candidate sources. Never fetches or extracts anything."""
    provider = discovery_providers.configured_provider(provider_name)
    if provider is None:
        return DiscoveryOutcome(
            query=query,
            provider="none",
            warnings=[
                "No source discovery provider is configured. Add TAVILY_API_KEY, "
                "EXA_API_KEY or JINA_API_KEY to enable this step."
            ],
        )

    candidates = provider.search(
        DiscoveryQuery(
            query=query,
            max_results=max(1, min(max_results, 25)),
            include_domains=include_domains or [],
        )
    )

    if logger:
        logger.log(
            "discovery",
            "sources_found",
            provider=provider.id,
            results=len(candidates),
        )

    warnings: list[str] = []
    if not candidates:
        warnings.append("The provider returned no usable public sources for that question.")

    return DiscoveryOutcome(
        query=query,
        provider=provider.id,
        candidates=candidates,
        warnings=warnings,
    )


def firecrawl_search(query: str, limit: int = 10) -> DiscoveryOutcome:
    """Optional extra discovery path when Firecrawl is configured."""
    from ..engines.firecrawl_engine import FirecrawlEngine

    engine = FirecrawlEngine()
    if not engine.available():
        return DiscoveryOutcome(
            query=query, provider="firecrawl", warnings=["Firecrawl is not configured."]
        )

    results = engine.search(query, limit=limit)
    candidates = [
        SourceCandidate(
            url=str(item.get("url", "")),
            title=str(item.get("title", "")),
            snippet=str(item.get("description", ""))[:400],
            provider="firecrawl",
        )
        for item in results
        if item.get("url")
    ]
    return DiscoveryOutcome(query=query, provider="firecrawl", candidates=candidates)
