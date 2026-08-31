"""JSON / REST API engine (Tier 1).

Calls a JSON endpoint directly with HTTPX and walks pagination (page number,
offset/limit or cursor). This is the route the router prefers whenever a
public endpoint was observed, because it is the fastest and most reproducible
way to obtain the same data twice.
"""

from __future__ import annotations

import time
from typing import Any

from ..config import SETTINGS
from ..discovery.structured_data import find_record_arrays, flatten_record
from ..exceptions import ErrorCode, ScraperError
from ..logging_config import RunLogger
from ..models import (
    CandidateDataset,
    ExtractionRequest,
    ExtractionResult,
    ExtractionSchema,
    PaginationType,
)
from .base import BaseEngine, detect_schema_drift
from .http_client import fetch


def resolve_path(payload: Any, path: str | None) -> Any:
    """Walk a dotted/indexed path such as ``data.items`` or ``results[0].rows``."""
    if not path or path in {"$", ""}:
        return payload
    node = payload
    for raw_part in path.split("."):
        part = raw_part.strip()
        if not part:
            continue
        while "[" in part:
            key, _, rest = part.partition("[")
            index_text, _, part = rest.partition("]")
            if key:
                node = node[key] if isinstance(node, dict) else None
            if node is None:
                return None
            try:
                node = node[int(index_text)]
            except (ValueError, IndexError, TypeError, KeyError):
                return None
            part = part.lstrip(".")
            if not part:
                break
        if part:
            if isinstance(node, dict):
                node = node.get(part)
            else:
                return None
        if node is None:
            return None
    return node


def records_from_payload(
    payload: Any, records_path: str | None
) -> tuple[list[dict[str, Any]], str | None]:
    """Return ``(records, path_used)`` for a JSON document."""
    if records_path:
        node = resolve_path(payload, records_path)
        if isinstance(node, list):
            # An explicit path that resolves to an empty list means "no more
            # records" — never fall back to a different part of the document.
            return [flatten_record(item) for item in node if isinstance(item, dict)], records_path
    else:
        node = payload
    if isinstance(node, list):
        rows = [item for item in node if isinstance(item, dict)]
        if rows:
            return [flatten_record(row) for row in rows], records_path
        if node and all(not isinstance(item, (dict, list)) for item in node):
            return [{"value": item} for item in node], records_path

    arrays = find_record_arrays(payload)
    if arrays:
        best = arrays[0]
        found = resolve_path(payload, None if best["path"] == "$" else best["path"])
        if isinstance(found, list):
            return (
                [flatten_record(item) for item in found if isinstance(item, dict)],
                None if best["path"] == "$" else best["path"],
            )
    if isinstance(payload, dict):
        return [flatten_record(payload)], records_path
    return [], records_path


class JsonApiEngine(BaseEngine):
    name = "json_api"
    label = "Direct JSON API"
    capabilities = {"json", "pagination", "local"}
    tier = 1
    cost_mode = "free"
    reliability = 0.92
    speed = 0.95

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
        payload_config = (candidate.payload if candidate else {}) or {}
        url = str(payload_config.get("url") or request.url)
        records_path = request.records_path or payload_config.get("records_path")

        plan = request.pagination
        max_pages = min(
            limit_pages or request.max_pages or 1,
            plan.max_pages if plan.max_pages > 1 else request.max_pages or 1,
            SETTINGS.limits.hard_max_pages,
        )
        max_rows = request.max_rows or SETTINGS.limits.max_rows

        all_records: list[dict[str, Any]] = []
        source_urls: list[str] = []
        warnings: list[str] = []
        baseline_columns: list[str] = []
        drift: list[str] = []
        pages_requested = 0
        pages_successful = 0
        seen_hashes: set[int] = set()
        cursor_value: str | None = None
        current_url = url

        for page_index in range(max_pages):
            page_number = plan.start + page_index * max(plan.step, 1)
            target = self._page_url(current_url, plan, page_number, cursor_value)
            pages_requested += 1
            if progress:
                progress(page_index + 1, max_pages, target)

            try:
                response = fetch(
                    target,
                    method=request.options.method,
                    headers=request.options.headers or None,
                    cookies=request.options.cookies or None,
                    params=request.options.params or None,
                    data=request.options.body,
                    timeout=request.options.timeout,
                    requests_per_second=request.options.requests_per_second,
                    max_bytes=SETTINGS.limits.max_download_bytes,
                )
            except ScraperError as exc:
                if page_index == 0:
                    raise
                warnings.append(f"Stopped at page {page_index + 1}: {exc.message()}")
                break

            try:
                document = response.json()
            except Exception as exc:
                if page_index == 0:
                    raise ScraperError(
                        ErrorCode.CONTENT_UNSUPPORTED, "The endpoint did not return valid JSON."
                    ) from exc
                warnings.append(f"Page {page_index + 1} did not return JSON; stopping.")
                break

            page_records, used_path = records_from_payload(document, records_path)
            records_path = records_path or used_path
            pages_successful += 1
            source_urls.append(response.url)

            if not page_records:
                if page_index == 0:
                    raise ScraperError(
                        ErrorCode.NO_DATA_DETECTED, "The endpoint returned no records."
                    )
                break

            page_hash = hash(tuple(sorted(str(sorted(r.items()))[:200] for r in page_records[:20])))
            if page_hash in seen_hashes:
                warnings.append("Pagination returned an already-seen page, so it was stopped.")
                break
            seen_hashes.add(page_hash)

            if not baseline_columns:
                baseline_columns = list(page_records[0].keys())
            else:
                drift.extend(detect_schema_drift(page_records, baseline_columns))

            if request.add_provenance_columns:
                for record in page_records:
                    record.setdefault("_source_url", response.url)
                    record.setdefault("_source_page", page_index + 1)

            all_records.extend(page_records)
            if logger:
                logger.log(
                    "json_api",
                    "page_extracted",
                    url=response.url,
                    engine=self.name,
                    page=page_index + 1,
                    rows=len(page_records),
                )

            if len(all_records) >= max_rows:
                all_records = all_records[:max_rows]
                warnings.append(f"Stopped at the row limit ({max_rows:,}).")
                break

            if plan.type == PaginationType.CURSOR:
                cursor_value = self._next_cursor(document, plan.cursor_path)
                if not cursor_value:
                    break
            elif plan.type == PaginationType.NONE:
                break
            elif plan.stop_when_empty and len(page_records) == 0:
                break

        columns = list(dict.fromkeys(key for record in all_records for key in record))
        return self._result(
            success=bool(all_records),
            records=all_records,
            columns=columns,
            source_urls=list(dict.fromkeys(source_urls)),
            started=started,
            pages_requested=pages_requested,
            pages_successful=pages_successful,
            warnings=warnings,
            schema_drift=list(dict.fromkeys(drift))[:10],
            metadata={"records_path": records_path, "pagination": plan.type.value},
        )

    # ------------------------------------------------------------------ helpers
    def _page_url(self, url: str, plan, page_number: int, cursor: str | None) -> str:
        from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

        if plan.type == PaginationType.NONE or page_number == plan.start and not cursor:
            if plan.type != PaginationType.CURSOR:
                if plan.url_template and "{page}" in plan.url_template:
                    return plan.url_template.replace("{page}", str(page_number))
                return url
        if (
            plan.type in {PaginationType.PAGE_NUMBER, PaginationType.OFFSET_LIMIT}
            and plan.url_template
        ):
            value = (
                page_number
                if plan.type == PaginationType.PAGE_NUMBER
                else (page_number - plan.start) * plan.step
            )
            return plan.url_template.replace("{page}", str(value))
        if plan.type == PaginationType.CURSOR and cursor:
            parts = urlsplit(url)
            query = dict(parse_qsl(parts.query))
            param = (plan.param or plan.cursor_path or "cursor").split(".")[-1]
            query[param] = cursor
            return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
        return url

    def _next_cursor(self, document: Any, cursor_path: str | None) -> str | None:
        if not cursor_path:
            return None
        value = resolve_path(document, cursor_path)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value)
        return None
