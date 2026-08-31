"""ScrapeGraphAI adapter (audit section G).

Uses the official ``scrapegraph-py`` SDK. Two capabilities are wired:

* ``extract`` — prompt/schema-driven structured extraction;
* ``scrape``  — page content when structure is not needed.

Cloud and metered: it runs only when the researcher allows cloud providers and
``SGAI_API_KEY`` is configured. Results are validated before they become a
dataset, so a provider that returns prose instead of records fails loudly
rather than producing a fake table.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from ..exceptions import ErrorCode, ScraperError
from ..logging_config import RunLogger
from ..models import CandidateDataset, ExtractionRequest, ExtractionResult, ExtractionSchema
from ..security.url_guard import guard_url
from .base import Availability, BaseEngine


def _records_from(payload: Any) -> list[dict[str, Any]]:
    """Find the record list in whatever shape the provider returned."""
    if payload is None:
        return []
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return []
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("result", "data", "records", "items", "rows", "results", "output"):
            nested = payload.get(key)
            if isinstance(nested, list):
                rows = [row for row in nested if isinstance(row, dict)]
                if rows:
                    return rows
            if isinstance(nested, dict):
                rows = _records_from(nested)
                if rows:
                    return rows
        scalar = {k: v for k, v in payload.items() if not isinstance(v, (dict, list))}
        return [scalar] if scalar else []
    return []


class ScrapeGraphEngine(BaseEngine):
    name = "scrapegraph"
    label = "ScrapeGraphAI (cloud)"
    capabilities = {"semantic_extraction", "structured_output", "javascript", "hosted"}
    tier = 4
    cost_mode = "metered"
    deterministic = False
    reliability = 0.72
    speed = 0.55
    requires_package = "scrapegraph_py"
    requires_credentials = "scrapegraph"

    def availability(self) -> Availability:
        try:
            import scrapegraph_py  # noqa: F401
        except Exception:
            return Availability(
                False,
                "Optional package not installed.",
                "pip install 'scrapegraph-py>=2.1.0'  (needs Python 3.12+)",
            )
        if not os.getenv("SGAI_API_KEY", "").strip():
            return Availability(
                False, "API key not configured.", "Set SGAI_API_KEY in your .env file."
            )
        return Availability(True)

    def _client(self):  # pragma: no cover - requires the optional SDK
        from scrapegraph_py import ScrapeGraphAI  # type: ignore

        return ScrapeGraphAI(api_key=os.environ["SGAI_API_KEY"])

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
                "Cloud providers are switched off for this run, so nothing is sent to ScrapeGraphAI.",
            )
        status = self.availability()
        if not status.ready:
            code = (
                ErrorCode.API_KEY_MISSING
                if "key" in status.reason.lower()
                else ErrorCode.OPTIONAL_ENGINE_NOT_INSTALLED
            )
            raise ScraperError(code, status.reason, {"install_hint": status.install_hint})

        guarded = guard_url(request.url)
        wanted = schema.field_names() if schema and schema.fields else []
        prompt = request.user_goal or (
            f"Extract these fields as a list of records: {', '.join(wanted)}"
            if wanted
            else "Extract the main tabular dataset on this page as a list of records."
        )

        records = self._call(guarded.url, prompt, wanted)
        if not records:
            raise ScraperError(
                ErrorCode.NO_DATA_DETECTED, "ScrapeGraphAI returned no structured records."
            )

        if request.add_provenance_columns:
            for record in records:
                record.setdefault("_source_url", guarded.url)

        max_rows = request.max_rows or 500_000
        truncated = len(records) > max_rows
        records = records[:max_rows]

        if logger:
            logger.log(
                "scrapegraph",
                "extract_complete",
                url=guarded.url,
                engine=self.name,
                rows=len(records),
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
            metadata={"provider": "scrapegraph", "metered": True, "prompt_used": True},
        )

    def _call(
        self, url: str, prompt: str, wanted: list[str]
    ) -> list[dict[str, Any]]:  # pragma: no cover
        client = self._client()
        schema_hint: dict[str, Any] | None = None
        if wanted:
            schema_hint = {
                "type": "object",
                "properties": {
                    "records": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {name: {"type": "string"} for name in wanted},
                        },
                    }
                },
            }

        try:
            if schema_hint is not None:
                response = client.extract(prompt=prompt, url=url, schema=schema_hint)
            else:
                response = client.extract(prompt=prompt, url=url)
        except TypeError:
            # Older SDK generations expose smartscraper(website_url=, user_prompt=).
            response = client.smartscraper(website_url=url, user_prompt=prompt)
        except Exception as exc:
            raise ScraperError(
                ErrorCode.HTTP_ERROR, f"ScrapeGraphAI failed ({exc.__class__.__name__})."
            ) from exc

        payload = getattr(response, "data", None)
        if payload is None and isinstance(response, dict):
            payload = response.get("data", response)
        return _records_from(payload if payload is not None else response)
