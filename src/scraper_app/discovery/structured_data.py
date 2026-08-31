"""Structured metadata and embedded application state (spec sections 4F / 4G).

Covers JSON-LD, microdata, RDFa, OpenGraph (via ``extruct`` when installed,
with an lxml fallback) and serialized app state such as ``__NEXT_DATA__``.
"""

from __future__ import annotations

import json
import re
from typing import Any

from lxml import html as lxml_html

_JSON_SCRIPT_TYPES = {
    "application/ld+json",
    "application/json",
    "application/x-json",
}

_STATE_PATTERNS = [
    re.compile(r"window\.__NUXT__\s*=\s*(\{.*?\});", re.DOTALL),
    re.compile(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});", re.DOTALL),
    re.compile(r"window\.__PRELOADED_STATE__\s*=\s*(\{.*?\});", re.DOTALL),
    re.compile(r"window\.__APOLLO_STATE__\s*=\s*(\{.*?\});", re.DOTALL),
]

MAX_JSON_CHARS = 2_000_000


def extract_json_ld(html: str) -> list[Any]:
    """Return every parsed JSON-LD document in the page."""
    documents: list[Any] = []
    try:
        tree = lxml_html.fromstring(html)
    except Exception:
        return documents
    for script in tree.xpath("//script[@type]"):
        script_type = (script.get("type") or "").lower().strip()
        if script_type != "application/ld+json":
            continue
        payload = (script.text_content() or "")[:MAX_JSON_CHARS]
        try:
            documents.append(json.loads(payload))
        except Exception:
            continue
    return documents


def extract_embedded_json(html: str) -> list[dict[str, Any]]:
    """Return embedded JSON blobs: ``<script type=application/json>`` + app state."""
    blobs: list[dict[str, Any]] = []
    try:
        tree = lxml_html.fromstring(html)
    except Exception:
        tree = None

    if tree is not None:
        for script in tree.xpath("//script"):
            script_type = (script.get("type") or "").lower().strip()
            script_id = script.get("id") or ""
            if script_type not in _JSON_SCRIPT_TYPES and script_id != "__NEXT_DATA__":
                continue
            if script_type == "application/ld+json":
                continue
            payload = (script.text_content() or "").strip()[:MAX_JSON_CHARS]
            if not payload:
                continue
            try:
                data = json.loads(payload)
            except Exception:
                continue
            blobs.append(
                {
                    "name": script_id or "inline_json",
                    "data": data,
                    "source": "script_json",
                }
            )

    for pattern in _STATE_PATTERNS:
        match = pattern.search(html or "")
        if not match:
            continue
        try:
            data = json.loads(match.group(1)[:MAX_JSON_CHARS])
        except Exception:
            continue
        blobs.append({"name": "app_state", "data": data, "source": "window_state"})

    return blobs


def extract_with_extruct(html: str, base_url: str) -> dict[str, Any]:
    """Full metadata extraction when ``extruct`` is available (optional)."""
    try:
        import extruct  # type: ignore
    except Exception:
        return {}
    try:
        return extruct.extract(
            html,
            base_url=base_url,
            syntaxes=["json-ld", "microdata", "rdfa", "opengraph", "dublincore"],
            uniform=True,
        )
    except Exception:
        return {}


def structured_types(metadata: dict[str, Any], json_ld: list[Any]) -> list[str]:
    """Collect the schema.org ``@type`` values present on the page."""
    types: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            value = node.get("@type") or node.get("type")
            if isinstance(value, str):
                types.add(value)
            elif isinstance(value, list):
                types.update(str(v) for v in value if isinstance(v, str))
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(json_ld)
    for syntax, payload in (metadata or {}).items():
        if syntax == "opengraph" and payload:
            types.add("OpenGraph")
        else:
            walk(payload)
    return sorted(types)[:25]


def find_record_arrays(data: Any, path: str = "", depth: int = 0) -> list[dict[str, Any]]:
    """Locate arrays of homogeneous objects inside a JSON document.

    Returns descriptors ``{path, count, keys, sample}`` sorted by usefulness —
    this is what turns an embedded blob into a candidate dataset.
    """
    found: list[dict[str, Any]] = []
    if depth > 6:
        return found

    if isinstance(data, list):
        objects = [item for item in data if isinstance(item, dict)]
        if len(objects) >= 2 and len(objects) >= len(data) * 0.6:
            keys: list[str] = []
            for item in objects[:50]:
                for key in item:
                    if key not in keys:
                        keys.append(key)
            found.append(
                {
                    "path": path or "$",
                    "count": len(objects),
                    "keys": keys[:60],
                    "sample": objects[:3],
                }
            )
        for index, item in enumerate(data[:3]):
            found.extend(find_record_arrays(item, f"{path}[{index}]", depth + 1))
    elif isinstance(data, dict):
        for key, value in data.items():
            child_path = f"{path}.{key}" if path else str(key)
            found.extend(find_record_arrays(value, child_path, depth + 1))

    found.sort(key=lambda item: (item["count"], len(item["keys"])), reverse=True)
    return found[:12]


def flatten_record(record: dict[str, Any], prefix: str = "", depth: int = 0) -> dict[str, Any]:
    """Flatten one nested record into scalar columns (bounded depth)."""
    flat: dict[str, Any] = {}
    for key, value in record.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict) and depth < 3:
            flat.update(flatten_record(value, f"{name}.", depth + 1))
        elif isinstance(value, list):
            if value and all(isinstance(v, (str, int, float, bool)) or v is None for v in value):
                flat[name] = ", ".join("" if v is None else str(v) for v in value[:20])
            elif value and isinstance(value[0], dict) and depth < 2:
                flat.update(flatten_record(value[0], f"{name}.0.", depth + 1))
            else:
                flat[name] = json.dumps(value)[:500] if value else None
        else:
            flat[name] = value
    return flat
