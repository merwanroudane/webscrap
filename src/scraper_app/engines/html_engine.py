"""Deterministic HTML engines (Tier 1).

* :class:`RepeatedDomEngine` — repeated card/list/row structures, optionally
  driven by a user-supplied CSS selector or XPath (Advanced mode).
* :class:`StructuredDataEngine` — JSON-LD / microdata / embedded app JSON.
* :class:`LinksEngine` — links and downloadable files as a dataset.
* :class:`FeedEngine` — RSS/Atom entries.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urljoin

from lxml import html as lxml_html

from ..config import SETTINGS
from ..discovery import file_detector, repeated_patterns, sitemap
from ..discovery import structured_data as sd
from ..exceptions import ErrorCode, ScraperError
from ..logging_config import RunLogger
from ..models import (
    CandidateDataset,
    ExtractionRequest,
    ExtractionResult,
    ExtractionSchema,
    FieldSpec,
)
from .base import BaseEngine, detect_schema_drift
from .http_client import fetch
from .pagination_support import iter_pages


def _fetcher_for(request: ExtractionRequest):
    def _fetch(url: str):
        return fetch(
            url,
            headers=request.options.headers or None,
            cookies=request.options.cookies or None,
            timeout=request.options.timeout,
            requests_per_second=request.options.requests_per_second,
        )

    return _fetch


def _rows_from_xpath(html: str, xpath: str, base_url: str) -> list[dict[str, Any]]:
    try:
        tree = lxml_html.fromstring(html)
        nodes = tree.xpath(xpath)
    except Exception as exc:
        raise ScraperError(ErrorCode.SELECTOR_NOT_FOUND, f"Invalid XPath: {exc}") from exc
    rows: list[dict[str, Any]] = []
    for node in nodes:
        if isinstance(node, str):
            rows.append({"value": node.strip()})
            continue
        row: dict[str, Any] = {"text": " ".join((node.text_content() or "").split())}
        href = node.get("href") if hasattr(node, "get") else None
        if href:
            row["link"] = urljoin(base_url, href)
        rows.append(row)
    return rows


class RepeatedDomEngine(BaseEngine):
    name = "repeated_dom"
    label = "Repeated page structure"
    capabilities = {"static_html", "pagination", "crawl", "local"}
    tier = 1
    cost_mode = "free"
    reliability = 0.82
    speed = 0.88

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
        payload = (candidate.payload if candidate else {}) or {}
        selector = request.selector or payload.get("selector")
        fields = (
            [FieldSpec(**f) for f in payload.get("fields", [])] if payload.get("fields") else []
        )
        if schema and schema.fields:
            fields = schema.fields

        all_records: list[dict[str, Any]] = []
        source_urls: list[str] = []
        warnings: list[str] = []
        drift: list[str] = []
        baseline: list[str] = []
        pages_requested = 0
        pages_successful = 0
        max_rows = request.max_rows or SETTINGS.limits.max_rows

        for page in iter_pages(
            request,
            fetcher=_fetcher_for(request),
            limit_pages=limit_pages,
            progress=progress,
            logger=logger,
        ):
            pages_requested += 1
            if page.error:
                if pages_successful == 0:
                    raise page.error
                warnings.append(f"Stopped at page {pages_requested}: {page.error.message()}")
                break

            if request.xpath:
                rows = _rows_from_xpath(page.html, request.xpath, page.url)
            elif selector:
                rows = repeated_patterns.extract_rows_with_selector(
                    page.html, selector, fields, page.url
                )
            else:
                detected = repeated_patterns.detect_repeated_patterns(page.html, page.url)
                if not detected:
                    rows = []
                else:
                    selector = detected[0].selector
                    fields = fields or detected[0].fields
                    rows = repeated_patterns.extract_rows_with_selector(
                        page.html, selector, fields, page.url
                    )

            if not rows:
                if pages_successful == 0:
                    raise ScraperError(
                        ErrorCode.SELECTOR_NOT_FOUND
                        if (selector or request.xpath)
                        else ErrorCode.NO_DATA_DETECTED,
                        "No repeated items matched on this page.",
                    )
                warnings.append(f"Page {pages_requested} produced no rows; stopping.")
                break

            if not baseline:
                baseline = list(rows[0].keys())
            else:
                drift.extend(detect_schema_drift(rows, baseline))

            if request.add_provenance_columns:
                for row in rows:
                    row.setdefault("_source_url", page.url)
                    row.setdefault("_source_page", page.number)

            all_records.extend(rows)
            pages_successful += 1
            source_urls.append(page.url)
            if logger:
                logger.log(
                    "repeated_dom",
                    "page_extracted",
                    url=page.url,
                    engine=self.name,
                    page=page.number,
                    rows=len(rows),
                )
            if len(all_records) >= max_rows:
                all_records = all_records[:max_rows]
                warnings.append(f"Stopped at the row limit ({max_rows:,}).")
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
            metadata={"selector": selector, "xpath": request.xpath},
        )


class StructuredDataEngine(BaseEngine):
    name = "structured"
    label = "Structured metadata"
    capabilities = {"static_html", "structured_output", "local"}
    tier = 1
    cost_mode = "free"
    reliability = 0.8
    speed = 0.9

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
        response = fetch(request.url, headers=request.options.headers or None)
        html = response.text

        documents = sd.extract_json_ld(html)
        blobs = sd.extract_embedded_json(html)
        records: list[dict[str, Any]] = []

        for document in documents:
            items = document if isinstance(document, list) else [document]
            for item in items:
                if isinstance(item, dict):
                    graph = item.get("@graph")
                    if isinstance(graph, list):
                        records.extend(
                            sd.flatten_record(node) for node in graph if isinstance(node, dict)
                        )
                    else:
                        records.append(sd.flatten_record(item))

        if not records:
            for blob in blobs:
                arrays = sd.find_record_arrays(blob["data"])
                if arrays:
                    from .json_engine import resolve_path

                    node = resolve_path(
                        blob["data"], None if arrays[0]["path"] == "$" else arrays[0]["path"]
                    )
                    if isinstance(node, list):
                        records.extend(
                            sd.flatten_record(item) for item in node if isinstance(item, dict)
                        )
                        break

        if not records:
            raise ScraperError(
                ErrorCode.NO_DATA_DETECTED, "No structured metadata records were found."
            )

        if request.add_provenance_columns:
            for record in records:
                record.setdefault("_source_url", response.url)

        columns = list(dict.fromkeys(key for record in records for key in record))
        return self._result(
            success=True,
            records=records[: request.max_rows or SETTINGS.limits.max_rows],
            columns=columns,
            source_urls=[response.url],
            started=started,
            pages_requested=1,
            pages_successful=1,
            metadata={"json_ld_documents": len(documents), "embedded_blobs": len(blobs)},
        )


class LinksEngine(BaseEngine):
    name = "links"
    label = "Links and files"
    capabilities = {"static_html", "crawl", "local"}
    tier = 1
    cost_mode = "free"
    reliability = 0.95
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
        payload = (candidate.payload if candidate else {}) or {}
        response = fetch(request.url, headers=request.options.headers or None)
        html = response.text

        try:
            tree = lxml_html.fromstring(html)
        except Exception as exc:
            raise ScraperError(
                ErrorCode.CONTENT_UNSUPPORTED, "The page could not be parsed."
            ) from exc

        pairs: list[tuple[str, str]] = []
        for anchor in tree.xpath("//a[@href]"):
            href = (anchor.get("href") or "").strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            absolute = urljoin(response.url, href)
            if absolute.startswith(("http://", "https://")):
                pairs.append((absolute, " ".join((anchor.text_content() or "").split())))

        if payload.get("files") is not None or payload.get("kind") == "files":
            records = file_detector.collect_file_links(pairs)
        else:
            records = [{"url": url, "text": text} for url, text in dict(pairs).items()]

        if not records:
            raise ScraperError(ErrorCode.NO_DATA_DETECTED, "No links were found on this page.")

        if request.add_provenance_columns:
            for record in records:
                record.setdefault("_source_url", response.url)

        return self._result(
            success=True,
            records=records[: request.max_rows or SETTINGS.limits.max_rows],
            columns=list(records[0].keys()),
            source_urls=[response.url],
            started=started,
            pages_requested=1,
            pages_successful=1,
        )


class FeedEngine(BaseEngine):
    name = "feed"
    label = "RSS/Atom feed"
    capabilities = {"rss", "xml", "local"}
    tier = 0
    cost_mode = "free"
    reliability = 0.93
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
        payload = (candidate.payload if candidate else {}) or {}
        url = str(payload.get("feed_url") or request.url)
        response = fetch(url)
        records = sitemap.parse_feed(response.content)
        if not records:
            raise ScraperError(ErrorCode.NO_DATA_DETECTED, "The feed contained no entries.")
        if request.add_provenance_columns:
            for record in records:
                record.setdefault("_source_url", response.url)
        return self._result(
            success=True,
            records=records[: request.max_rows or SETTINGS.limits.max_rows],
            columns=list(records[0].keys()),
            source_urls=[response.url],
            started=started,
            pages_requested=1,
            pages_successful=1,
        )
