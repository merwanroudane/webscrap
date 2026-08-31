"""AgentQL adapter (audit section H).

AgentQL turns a small declarative query into structured data:

    { products[] { name price rating } }

Two integration paths, in preference order:

1. the documented REST endpoint ``POST https://api.agentql.com/v1/query-data``
   with an ``X-API-Key`` header — no browser needed, easy to test;
2. the ``agentql`` SDK wrapping a Playwright page, used when the SDK and a
   browser are both installed and the page needs rendering first.

It is never used where a direct API or a deterministic selector would do.
"""

from __future__ import annotations

import os
import time
from typing import Any

from ..config import SETTINGS
from ..exceptions import ErrorCode, ScraperError
from ..logging_config import RunLogger
from ..models import CandidateDataset, ExtractionRequest, ExtractionResult, ExtractionSchema
from ..security.url_guard import guard_url
from .base import Availability, BaseEngine

REST_ENDPOINT = "https://api.agentql.com/v1/query-data"


def build_query(fields: list[str], container: str = "items") -> str:
    """Build an AgentQL query from the researcher's field list."""
    safe = [f for f in (fields or []) if f.replace("_", "").isalnum()]
    if not safe:
        return "{ items[] { title link } }"
    return "{ " + container + "[] { " + " ".join(safe) + " } }"


def records_from_payload(payload: Any) -> list[dict[str, Any]]:
    """AgentQL returns ``{"data": {"items": [...]}}``; find the record list."""
    if isinstance(payload, dict):
        data = payload.get("data", payload)
        if isinstance(data, dict):
            for value in data.values():
                if isinstance(value, list):
                    rows = [row for row in value if isinstance(row, dict)]
                    if rows:
                        return rows
            scalar = {k: v for k, v in data.items() if not isinstance(v, (dict, list))}
            return [scalar] if scalar else []
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
    return []


class AgentQLEngine(BaseEngine):
    name = "agentql"
    label = "AgentQL (cloud)"
    capabilities = {"semantic_extraction", "structured_output", "javascript", "hosted"}
    tier = 4
    cost_mode = "metered"
    deterministic = False
    reliability = 0.7
    speed = 0.6
    requires_credentials = "agentql"

    def availability(self) -> Availability:
        # The REST path needs only a key, so the SDK is not required.
        if not os.getenv("AGENTQL_API_KEY", "").strip():
            return Availability(
                False, "API key not configured.", "Set AGENTQL_API_KEY in your .env file."
            )
        return Availability(True)

    def extract(
        self,
        request: ExtractionRequest,
        candidate: CandidateDataset | None = None,
        schema: ExtractionSchema | None = None,
        *,
        logger: RunLogger | None = None,
        progress=None,
        limit_pages: int | None = None,
    ) -> ExtractionResult:
        started = time.monotonic()
        if not request.allow_cloud:
            raise ScraperError(
                ErrorCode.NO_ROUTE,
                "Cloud providers are switched off for this run, so nothing is sent to AgentQL.",
            )
        status = self.availability()
        if not status.ready:
            raise ScraperError(
                ErrorCode.API_KEY_MISSING, status.reason, {"install_hint": status.install_hint}
            )

        guarded = guard_url(request.url)
        fields = schema.field_names() if schema and schema.fields else []
        if not fields and candidate is not None:
            fields = [str(c) for c in candidate.columns][:12]
        query = build_query(fields)

        payload = self._query_rest(guarded.url, query)
        records = records_from_payload(payload)
        if not records:
            raise ScraperError(
                ErrorCode.NO_DATA_DETECTED, "AgentQL returned no records for that query."
            )

        if request.add_provenance_columns:
            for record in records:
                record.setdefault("_source_url", guarded.url)

        max_rows = request.max_rows or SETTINGS.limits.max_rows
        truncated = len(records) > max_rows
        records = records[:max_rows]

        if logger:
            logger.log(
                "agentql", "extract_complete", url=guarded.url, engine=self.name, rows=len(records)
            )

        return self._result(
            success=True,
            records=records,
            columns=list(dict.fromkeys(key for record in records for key in record)),
            source_urls=[guarded.url],
            started=started,
            pages_requested=1,
            pages_successful=1,
            truncated=truncated,
            metadata={"provider": "agentql", "metered": True, "query": query},
        )

    def _query_rest(self, url: str, query: str) -> dict[str, Any]:
        import httpx

        body = {
            "url": url,
            "query": query,
            "params": {"wait_for": 0, "is_scroll_to_bottom_enabled": False},
        }
        try:
            with httpx.Client(timeout=SETTINGS.limits.browser_timeout) as client:
                response = client.post(
                    REST_ENDPOINT,
                    json=body,
                    headers={
                        "X-API-Key": os.environ["AGENTQL_API_KEY"],
                        "Content-Type": "application/json",
                    },
                )
        except httpx.TimeoutException as exc:
            raise ScraperError(ErrorCode.TIMEOUT, "AgentQL timed out.") from exc
        except httpx.HTTPError as exc:
            raise ScraperError(
                ErrorCode.CONNECTION_ERROR,
                f"AgentQL could not be reached ({exc.__class__.__name__}).",
            ) from exc

        if response.status_code in {401, 403}:
            raise ScraperError(ErrorCode.API_AUTH_REQUIRED, "AgentQL rejected the configured key.")
        if response.status_code >= 400:
            raise ScraperError(ErrorCode.HTTP_ERROR, f"AgentQL returned {response.status_code}.")
        try:
            return response.json()
        except Exception as exc:
            raise ScraperError(
                ErrorCode.CONTENT_UNSUPPORTED, "AgentQL returned a non-JSON response."
            ) from exc

    # ------------------------------------------------------------------ SDK path
    def sdk_available(self) -> bool:
        """True when the SDK path (Playwright page wrapping) could be used."""
        try:
            import agentql  # noqa: F401
        except Exception:
            return False
        from ..discovery.network_probe import playwright_available

        return playwright_available()[0]
