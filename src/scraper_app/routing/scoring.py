"""Router scoring (spec section 57).

The score is a documented, testable routing heuristic — not a statistical
probability. Weights are explicit so the Diagnostics tab can show exactly why
one engine outranked another.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..engines.base import BaseEngine
from ..models import CandidateDataset, ExtractionRequest

WEIGHTS = {
    "source_fit": 0.40,
    "determinism": 0.15,
    "reliability": 0.15,
    "speed": 0.10,
    "cost": 0.10,
    "user_preference": 0.10,
}

COST_SCORE = {"free": 1.0, "local_compute": 0.6, "metered": 0.2}

#: Preferred order when scores tie (spec section 108 routing policy).
TIER_ORDER = [
    "direct_file",
    "json_api",
    "feed",
    "structured",
    "table",
    "repeated_dom",
    "article",
    "document",
    "links",
    "playwright",
    "crawl4ai",
    "firecrawl",
]


@dataclass
class ScoredEngine:
    engine: str
    score: float
    components: dict[str, float]
    available: bool
    reason: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "engine": self.engine,
            "score": round(self.score, 3),
            "available": self.available,
            "reason": self.reason,
            **{k: round(v, 3) for k, v in self.components.items()},
        }


def score_engine(
    engine: BaseEngine,
    candidate: CandidateDataset | None,
    request: ExtractionRequest,
) -> ScoredEngine:
    """Score one engine for one candidate dataset."""
    availability = engine.availability()

    source_fit = 0.0
    if candidate is not None:
        source_fit = candidate.score if candidate.engine == engine.name else 0.0
        if candidate.engine != engine.name and engine.name in {"playwright", "crawl4ai", "firecrawl"}:
            # Generic renderers can serve any candidate, at a discount.
            source_fit = max(0.0, candidate.score - 0.3)

    components = {
        "source_fit": source_fit,
        "determinism": 1.0 if engine.deterministic else 0.4,
        "reliability": engine.reliability,
        "speed": engine.speed,
        "cost": COST_SCORE.get(engine.cost_mode, 0.5),
        "user_preference": 1.0 if request.engine_preference == engine.name else 0.5,
    }

    score = sum(WEIGHTS[key] * value for key, value in components.items())

    # Policy adjustments — never escalate merely because a tier is fancier.
    if engine.cost_mode == "metered" and not request.allow_cloud:
        score = 0.0
        availability_reason = "Cloud providers are switched off for this run."
    elif not engine.deterministic and not request.allow_ai and engine.name in {"firecrawl"}:
        score *= 0.5
        availability_reason = availability.reason
    elif engine.name == "playwright" and not request.allow_browser:
        score = 0.0
        availability_reason = "Browser mode is switched off for this run."
    else:
        availability_reason = availability.reason

    if not availability.ready:
        score *= 0.0 if engine.tier >= 3 else 0.2

    # Deterministic tie-break: lower tier order wins.
    if engine.name in TIER_ORDER:
        score += (len(TIER_ORDER) - TIER_ORDER.index(engine.name)) * 1e-4

    return ScoredEngine(
        engine=engine.name,
        score=round(score, 4),
        components=components,
        available=availability.ready,
        reason=availability_reason,
    )


def rank_engines(
    engines: dict[str, BaseEngine],
    candidate: CandidateDataset | None,
    request: ExtractionRequest,
) -> list[ScoredEngine]:
    scored = [score_engine(engine, candidate, request) for engine in engines.values()]
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored
