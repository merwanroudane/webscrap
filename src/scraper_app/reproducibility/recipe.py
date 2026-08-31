"""Extraction recipe (spec section 34).

A recipe is the reproducible description of a successful run: source, engine,
request shape, field mapping, pagination and limits. Credentials are stripped
before it is written — a recipe is meant to be shared.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import yaml

from ..config import APP_VERSION
from ..models import (
    CandidateDataset,
    ExtractionRequest,
    ExtractionResult,
    ExtractionSchema,
    RouteDecision,
)
from ..security.secrets import sanitize_url, strip_secrets

RECIPE_VERSION = "1.0"


def build(
    *,
    name: str,
    request: ExtractionRequest,
    candidate: CandidateDataset | None,
    result: ExtractionResult,
    decision: RouteDecision | None,
    schema: ExtractionSchema | None = None,
    cleaning: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble a recipe dictionary (already secret-free)."""
    payload: dict[str, Any] = {
        "recipe_version": RECIPE_VERSION,
        "app_version": APP_VERSION,
        "name": name,
        "source_url": sanitize_url(request.url),
        "mode": request.mode,
        "preset": request.preset,
        "engine": result.engine,
        "route_rationale": decision.rationale if decision else "",
        "dataset": {
            "kind": candidate.kind.value if candidate else None,
            "title": candidate.title if candidate else None,
            "selector": (candidate.payload or {}).get("selector") if candidate else None,
            "table_index": (candidate.payload or {}).get("table_index") if candidate else None,
            "records_path": result.metadata.get("records_path")
            or ((candidate.payload or {}).get("records_path") if candidate else None),
            "api_url": (candidate.payload or {}).get("url") if candidate else None,
        },
        "request": {
            "method": request.options.method,
            "params": request.options.params,
            "headers": dict.fromkeys(request.options.headers, "<set via environment variable>"),
            "selector": request.selector,
            "xpath": request.xpath,
            "wait_for": request.wait_for,
        },
        "pagination": json.loads(request.pagination.model_dump_json()),
        "crawl": json.loads(request.crawl.model_dump_json()),
        "limits": {
            "max_pages": request.max_pages,
            "max_rows": request.max_rows,
            "respect_robots": request.respect_robots,
            "same_domain_only": request.same_domain_only,
        },
        "fields": [
            {"name": f.name, "type": f.dtype, "required": f.required, "name_source": f.name_source.value}
            for f in (schema.fields if schema else [])
        ],
        "cleaning": cleaning or [],
        "provenance_columns": request.add_provenance_columns,
    }
    return strip_secrets(payload)


def recipe_hash(recipe: dict[str, Any]) -> str:
    blob = json.dumps(recipe, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def to_json_bytes(recipe: dict[str, Any]) -> bytes:
    return json.dumps(recipe, indent=2, ensure_ascii=False).encode("utf-8")


def to_yaml_bytes(recipe: dict[str, Any]) -> bytes:
    return yaml.safe_dump(recipe, sort_keys=False, allow_unicode=True).encode("utf-8")


def from_json(payload: bytes | str) -> dict[str, Any]:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    return json.loads(payload)


def to_request(recipe: dict[str, Any]) -> ExtractionRequest:
    """Rebuild an ExtractionRequest so a saved recipe can be re-run."""
    from ..models import CrawlPlan, PaginationPlan, RequestOptions

    limits = recipe.get("limits", {})
    request_block = recipe.get("request", {})
    return ExtractionRequest(
        url=recipe["source_url"],
        mode=recipe.get("mode", "auto"),
        preset=recipe.get("preset", "auto"),
        max_pages=int(limits.get("max_pages", 1) or 1),
        max_rows=limits.get("max_rows"),
        respect_robots=bool(limits.get("respect_robots", True)),
        same_domain_only=bool(limits.get("same_domain_only", True)),
        selector=request_block.get("selector"),
        xpath=request_block.get("xpath"),
        wait_for=request_block.get("wait_for"),
        records_path=(recipe.get("dataset") or {}).get("records_path"),
        engine_preference=recipe.get("engine"),
        options=RequestOptions(
            method=request_block.get("method", "GET"),
            params=request_block.get("params", {}) or {},
        ),
        pagination=PaginationPlan(**recipe.get("pagination", {})),
        crawl=CrawlPlan(**recipe.get("crawl", {})),
        add_provenance_columns=bool(recipe.get("provenance_columns", True)),
    )


def to_candidate(recipe: dict[str, Any]) -> CandidateDataset | None:
    """Rebuild the candidate dataset a recipe refers to."""
    from ..models import Confidence, DatasetKind

    dataset = recipe.get("dataset") or {}
    kind = dataset.get("kind")
    if not kind:
        return None
    payload: dict[str, Any] = {}
    if dataset.get("selector"):
        payload["selector"] = dataset["selector"]
    if dataset.get("table_index") is not None:
        payload["table_index"] = dataset["table_index"]
    if dataset.get("records_path"):
        payload["records_path"] = dataset["records_path"]
    if dataset.get("api_url"):
        payload["url"] = dataset["api_url"]
    return CandidateDataset(
        id="recipe",
        kind=DatasetKind(kind),
        title=dataset.get("title") or "Saved recipe dataset",
        engine=recipe.get("engine", "table"),
        score=0.9,
        confidence=Confidence.HIGH,
        payload=payload,
        why="Reproduced from a saved recipe.",
    )
