"""Research provenance manifest (spec section 30).

Every run produces one manifest describing where the data came from, how it was
obtained, what was cleaned and under which access status. Credentials never
appear in it.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import pandas as pd

from ..config import APP_VERSION, SETTINGS
from ..models import (
    ExtractionResult,
    ExtractionSchema,
    Provenance,
    RouteDecision,
    SourceProfile,
    utcnow,
)
from ..security.secrets import sanitize_url, strip_secrets

#: Which provider registry an engine's ``metadata["provider"]`` belongs to.
#: Used only to label provenance; it never affects behaviour.
_ENGINE_CATEGORY = {
    "remote_browser": "remote_browser",
    "managed_fetch": "managed_fetch",
    "semantic_content": "semantic_content",
    "document": "document",
    "firecrawl": "managed_fetch",
    "agentql": "managed_fetch",
    "scrapegraph": "managed_fetch",
}


def _external_services(result: ExtractionResult) -> dict[str, str | None]:
    """Name the external services a run used, without naming any credential.

    A methods section has to be able to say *which* service saw the query and
    which model produced a column. ``engine`` alone cannot answer that, because
    one engine fronts many vendors (audit v0.2 section 60).
    """
    metadata = result.metadata or {}
    provider_id = metadata.get("provider") or None
    category = _ENGINE_CATEGORY.get(result.engine) or (
        _ENGINE_CATEGORY.get(str(provider_id)) if provider_id else None
    )

    return {
        "provider_id": str(provider_id) if provider_id else None,
        "provider_category": category,
        "ai_provider": (str(metadata["ai_provider"]) if metadata.get("ai_provider") else None),
        "ai_model": str(metadata["ai_model"]) if metadata.get("ai_model") else None,
        "remote_browser_provider": (
            str(provider_id) if provider_id and category == "remote_browser" else None
        ),
        "managed_fetch_provider": (
            str(provider_id) if provider_id and category == "managed_fetch" else None
        ),
    }


def build(
    *,
    run_id: str,
    request_url: str,
    profile: SourceProfile | None,
    result: ExtractionResult,
    decision: RouteDecision | None,
    schema: ExtractionSchema | None,
    rows_clean: int,
    cleaning_operations: list[dict[str, Any]] | None = None,
    recipe_hash: str = "",
    started_at: datetime | None = None,
) -> Provenance:
    return Provenance(
        run_id=run_id,
        app_version=APP_VERSION,
        started_at=started_at or result.started_at,
        finished_at=result.finished_at or utcnow(),
        source_url=sanitize_url(request_url),
        final_url=sanitize_url(profile.final_url if profile else request_url),
        retrieved_at=result.started_at,
        engine=result.engine,
        engine_detail=decision.engine if decision else result.engine,
        route_rationale=decision.rationale if decision else "",
        pages_requested=result.pages_requested,
        pages_successful=result.pages_successful,
        rows_raw=result.rows,
        rows_clean=rows_clean,
        columns=list(result.columns),
        field_schema=schema.model_dump() if schema else {},
        recipe_hash=recipe_hash,
        robots_status=profile.robots.state if profile else "not_checked",
        robots_url=profile.robots.robots_url if profile else None,
        user_agent=SETTINGS.user_agent,
        warnings=list(result.warnings),
        cleaning_operations=list(cleaning_operations or []),
        used_ai=bool(decision.uses_ai) if decision else False,
        used_cloud_provider=(result.engine if decision and decision.uses_cloud else None),
        **_external_services(result),
    )


def to_json_bytes(provenance: Provenance) -> bytes:
    payload = strip_secrets(json.loads(provenance.model_dump_json()))
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


def to_frame(provenance: Provenance) -> pd.DataFrame:
    """Flat key/value view used for the CSV export and the Sources tab."""
    payload = json.loads(provenance.model_dump_json())
    rows = []
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)[:2000]
        rows.append({"field": key, "value": value})
    return pd.DataFrame(rows)


def to_csv_bytes(provenance: Provenance) -> bytes:
    return to_frame(provenance).to_csv(index=False).encode("utf-8-sig")
