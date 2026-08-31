"""Normalizing what an agentic engine hands back (audit v0.2 sections 34-35).

Browser Use, Stagehand and Skyvern do not agree on a return type. Depending on
the task and the version, a run can end with:

* a list of dicts, or a dict wrapping one — already the records we want;
* a JSON string of either of those;
* a full HTML page, when the agent simply navigated somewhere;
* a sentence of natural language ("I found 12 products, the cheapest is ...").

The first version of these engines called ``str(...)`` on all of it and fed the
result to an HTML parser. For the HTML case that worked. For the JSON case the
parser found no elements and the run failed with "no data" even though the agent
had succeeded, and for the natural-language case the text was silently discarded.

So the type is classified first, and text that is *only* prose is reported as a
typed error rather than being passed off as a dataset. An agent's sentence is
not data, and a research tool must not pretend otherwise.
"""

from __future__ import annotations

import json
import re
from typing import Any

#: Enough of a tag soup to be worth handing to the DOM parser.
_HTML_HINT = re.compile(r"<\s*(html|body|table|div|ul|ol|section|article|tr|li)\b", re.I)


def _records_from_mapping(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Find the record list inside a wrapper object like ``{"data": [...]}``."""
    for key in ("records", "data", "items", "results", "rows", "output", "extracted"):
        value = payload.get(key)
        if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            return [dict(item) for item in value]
        if isinstance(value, dict):
            nested = _records_from_mapping(value)
            if nested:
                return nested

    # A single flat record is still a record, as long as it holds scalars.
    if payload and all(not isinstance(v, (dict, list)) for v in payload.values()):
        return [dict(payload)]
    return None


def records_from_object(payload: Any) -> list[dict[str, Any]] | None:
    """Records from an already-parsed JSON value, or ``None``."""
    if isinstance(payload, list):
        if payload and all(isinstance(item, dict) for item in payload):
            return [dict(item) for item in payload]
        if payload and all(not isinstance(item, (dict, list)) for item in payload):
            # A bare list of values is a one-column table.
            return [{"value": item} for item in payload]
        return None
    if isinstance(payload, dict):
        return _records_from_mapping(payload)
    return None


def _maybe_json(text: str) -> Any | None:
    """Parse a JSON document, including one wrapped in a ``` fence."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped).strip()
    if not stripped.startswith(("{", "[")):
        return None
    try:
        return json.loads(stripped)
    except (ValueError, TypeError):
        return None


def classify(payload: Any) -> tuple[str, Any]:
    """Decide what an agent returned.

    Returns ``(kind, value)`` where ``kind`` is one of:

    ``records``  a list of dicts, ready to become rows
    ``html``     markup for the deterministic DOM extractors
    ``text``     prose — the agent talked instead of returning data
    ``empty``    nothing usable at all
    """
    if payload is None:
        return "empty", None

    # Pydantic models and other structured objects expose their own dict form.
    for attribute in ("model_dump", "dict"):
        method = getattr(payload, attribute, None)
        if callable(method) and not isinstance(payload, (dict, list, str, bytes)):
            try:
                payload = method()
                break
            except Exception:
                pass

    if isinstance(payload, (dict, list)):
        records = records_from_object(payload)
        if records:
            return "records", records
        return "empty", None

    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")

    if not isinstance(payload, str):
        payload = str(payload)

    text = payload.strip()
    if not text:
        return "empty", None

    parsed = _maybe_json(text)
    if parsed is not None:
        records = records_from_object(parsed)
        if records:
            return "records", records
        # Valid JSON that holds no records is empty, not prose. Reporting it as
        # prose would tell the user the agent "answered in words" when it did
        # not say anything at all.
        return "empty", None

    if _HTML_HINT.search(text):
        return "html", text

    return "text", text
