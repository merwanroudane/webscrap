"""Repeated DOM structure detection (spec section 24).

This is what makes one-click mode work on card lists, search results, product
grids and directories. It is fully deterministic: sibling groups with similar
structure are clustered, then field candidates are derived from headings,
links, images, time elements and labelled spans. No LLM is involved.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any
from urllib.parse import urljoin

from lxml import html as lxml_html

from ..config import SETTINGS
from ..models import Confidence, FieldSpec, NameSource, RepeatedPatternCandidate

_WS = re.compile(r"\s+")
_SKIP_TAGS = {"script", "style", "noscript", "svg", "path", "template", "br", "hr"}
_NOISE_CLASS = re.compile(
    r"(?i)(nav|menu|footer|header|breadcrumb|pagination|cookie|banner|social)"
)


def _text(node) -> str:
    return _WS.sub(" ", node.text_content() or "").strip()


def _signature(node, depth: int = 2) -> str:
    """Structural fingerprint: tag path + stable class tokens."""
    tag = node.tag if isinstance(node.tag, str) else "node"
    classes = " ".join(sorted((node.get("class") or "").split()))[:80]
    if depth <= 0:
        return f"{tag}.{classes}"
    children = [
        _signature(child, depth - 1)
        for child in node
        if isinstance(child.tag, str) and child.tag not in _SKIP_TAGS
    ][:6]
    return f"{tag}.{classes}[{'|'.join(children)}]"


def _css_selector(node) -> str:
    """Build a short, human-readable CSS selector for a repeated item."""
    tag = node.tag if isinstance(node.tag, str) else "div"
    classes = [c for c in (node.get("class") or "").split() if not c.isdigit()][:2]
    if classes:
        return tag + "".join(f".{c}" for c in classes)
    parent = node.getparent()
    if parent is not None and isinstance(parent.tag, str):
        parent_classes = [c for c in (parent.get("class") or "").split() if not c.isdigit()][:1]
        if parent_classes:
            return f"{parent.tag}.{parent_classes[0]} > {tag}"
        if parent.get("id"):
            return f"#{parent.get('id')} > {tag}"
    return tag


def _slug(text: str, fallback: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z؀-ۿ]+", "_", text).strip("_").lower()
    cleaned = re.sub(r"_+", "_", cleaned)
    return (cleaned or fallback)[:40]


def _item_fields(node, base_url: str | None) -> dict[str, Any]:
    """Extract labelled values from one repeated item."""
    row: dict[str, Any] = {}

    heading = node.xpath(".//h1|.//h2|.//h3|.//h4|.//h5")
    if heading:
        row["title"] = _text(heading[0])

    links = node.xpath(".//a[@href]")
    if links:
        href = links[0].get("href", "")
        row["link"] = urljoin(base_url, href) if base_url else href
        if "title" not in row:
            link_text = _text(links[0])
            if link_text:
                row["title"] = link_text

    images = node.xpath(".//img")
    if images:
        alt = (images[0].get("alt") or "").strip()
        src = images[0].get("src") or images[0].get("data-src") or ""
        if alt:
            row["image_alt"] = alt
        if src:
            row["image_url"] = urljoin(base_url, src) if base_url else src

    times = node.xpath(".//time")
    if times:
        row["date"] = (times[0].get("datetime") or _text(times[0]))[:60]

    # Elements carrying an explicit semantic class/itemprop become named fields.
    for element in node.xpath(".//*[@itemprop or @data-field or @class]"):
        tag = element.tag if isinstance(element.tag, str) else ""
        if tag in _SKIP_TAGS or tag in {"a", "img", "time"}:
            continue
        name = element.get("itemprop") or element.get("data-field")
        if not name:
            classes = [c for c in (element.get("class") or "").split() if len(c) > 2][:1]
            if not classes or tag not in {"span", "p", "div", "li", "strong", "em", "dd", "td"}:
                continue
            name = classes[0]
        value = _text(element)
        if not value or len(value) > 300:
            continue
        key = _slug(str(name), f"field_{len(row)}")
        if key in row or key in {"title", "link", "date"}:
            continue
        if len(row) >= 14:
            break
        row[key] = value

    if not row or set(row) <= {"link"}:
        text = _text(node)
        if text:
            row["text"] = text[:400]
    return row


def _infer_dtype(values: list[Any]) -> str:
    sample = [str(v) for v in values if v not in (None, "")]
    if not sample:
        return "string"
    numeric = sum(1 for v in sample if re.fullmatch(r"[-+]?[\d.,\s%$€£]+", v))
    if numeric >= len(sample) * 0.8:
        return "number"
    dateish = sum(1 for v in sample if re.search(r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}", v))
    if dateish >= len(sample) * 0.6:
        return "date"
    if all(v.startswith("http") for v in sample):
        return "url"
    return "string"


def detect_repeated_patterns(
    html: str,
    base_url: str | None = None,
    max_candidates: int | None = None,
    min_items: int | None = None,
) -> list[RepeatedPatternCandidate]:
    """Cluster sibling groups with a shared structure into dataset candidates."""
    max_candidates = max_candidates or SETTINGS.limits.max_repeated_candidates
    min_items = min_items or SETTINGS.limits.min_repeated_items

    try:
        tree = lxml_html.fromstring(html)
    except Exception:
        return []

    groups: dict[tuple[int, str], list] = defaultdict(list)
    for parent in tree.iter():
        if not isinstance(parent.tag, str) or parent.tag in _SKIP_TAGS:
            continue
        children = [
            child for child in parent if isinstance(child.tag, str) and child.tag not in _SKIP_TAGS
        ]
        if len(children) < min_items:
            continue
        signatures = Counter(_signature(child) for child in children)
        signature, count = signatures.most_common(1)[0]
        if count < min_items:
            continue
        matching = [child for child in children if _signature(child) == signature]
        groups[(id(parent), signature)] = matching

    candidates: list[RepeatedPatternCandidate] = []
    for (_parent_id, _signature_key), items in groups.items():
        first = items[0]
        parent = first.getparent()
        parent_class = (parent.get("class") or "") if parent is not None else ""
        if _NOISE_CLASS.search(parent_class) or _NOISE_CLASS.search(first.get("class") or ""):
            continue

        rows = [_item_fields(item, base_url) for item in items]
        rows = [row for row in rows if row]
        if len(rows) < min_items:
            continue

        key_counts = Counter(key for row in rows for key in row)
        keep = [key for key, count in key_counts.items() if count >= len(rows) * 0.5]
        if not keep:
            continue
        normalized = [{key: row.get(key) for key in keep} for row in rows]

        filled = sum(
            1 for row in normalized for key in keep if row.get(key) not in (None, "")
        ) / float(len(normalized) * len(keep))
        text_only = keep == ["text"]
        score = (
            0.35
            + 0.25 * min(len(rows) / 20.0, 1.0)
            + 0.25 * filled
            + 0.1 * min(len(keep) / 5.0, 1.0)
        )
        if text_only:
            score -= 0.25
        score = max(0.05, min(score, 0.95))

        fields = [
            FieldSpec(
                name=key,
                dtype=_infer_dtype([row.get(key) for row in normalized]),
                selector=None,
                name_source=NameSource.HEURISTIC,
                confidence=Confidence.from_score(key_counts[key] / len(normalized)),
                sample=next(
                    (str(row[key])[:80] for row in normalized if row.get(key) not in (None, "")),
                    None,
                ),
            )
            for key in keep
        ]

        candidates.append(
            RepeatedPatternCandidate(
                selector=_css_selector(first),
                item_count=len(normalized),
                fields=fields,
                sample_rows=normalized[:5],
                score=score,
                confidence=Confidence.from_score(score),
            )
        )

    candidates.sort(key=lambda c: (c.score, c.item_count), reverse=True)

    # Drop near-duplicate candidates that share a selector.
    unique: list[RepeatedPatternCandidate] = []
    seen_selectors: set[str] = set()
    for candidate in candidates:
        if candidate.selector in seen_selectors:
            continue
        seen_selectors.add(candidate.selector)
        unique.append(candidate)
        if len(unique) >= max_candidates:
            break
    return unique


def extract_rows_with_selector(
    html: str, selector: str, fields: list[FieldSpec], base_url: str | None = None
) -> list[dict[str, Any]]:
    """Re-apply a detected pattern to a new page (used during pagination)."""
    try:
        tree = lxml_html.fromstring(html)
    except Exception:
        return []
    try:
        nodes = tree.cssselect(selector)
    except Exception:
        return []
    names = [f.name for f in fields] or None
    rows: list[dict[str, Any]] = []
    for node in nodes:
        row = _item_fields(node, base_url)
        if not row:
            continue
        rows.append({name: row.get(name) for name in names} if names else row)
    return rows
