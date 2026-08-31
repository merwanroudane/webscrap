"""HTML table detection (spec section 23).

Fast path: ``pandas.read_html``. DOM path: lxml, used to recover headers,
captions and nearby headings that pandas discards, and to handle tables that
pandas refuses (single row, colspan-heavy layouts).
"""

from __future__ import annotations

import io
import re
from typing import Any

import pandas as pd
from lxml import html as lxml_html

from ..models import Confidence, TableCandidate

_WS = re.compile(r"\s+")


def _clean_cell(value: Any) -> Any:
    if isinstance(value, str):
        return _WS.sub(" ", value).strip()
    return value


def _clean_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [
            " ".join(str(part) for part in col if str(part) and "Unnamed" not in str(part)).strip()
            or f"column_{i}"
            for i, col in enumerate(df.columns)
        ]
    df.columns = [
        _WS.sub(" ", str(c)).strip() or f"column_{i}" for i, c in enumerate(df.columns)
    ]
    # De-duplicate column names deterministically.
    seen: dict[str, int] = {}
    columns: list[str] = []
    for col in df.columns:
        if col in seen:
            seen[col] += 1
            columns.append(f"{col}_{seen[col]}")
        else:
            seen[col] = 0
            columns.append(col)
    df.columns = columns
    return df.map(_clean_cell) if hasattr(df, "map") else df.applymap(_clean_cell)


def _context_for(node) -> tuple[str | None, str | None]:
    """Return ``(caption, preceding heading)`` for a table element."""
    caption = None
    caption_nodes = node.xpath("./caption")
    if caption_nodes:
        caption = _WS.sub(" ", caption_nodes[0].text_content()).strip()[:200] or None

    heading = None
    previous = node.getprevious()
    hops = 0
    while previous is not None and hops < 6:
        tag = str(previous.tag).lower() if isinstance(previous.tag, str) else ""
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6", "caption"}:
            heading = _WS.sub(" ", previous.text_content()).strip()[:200] or None
            break
        previous = previous.getprevious()
        hops += 1
    if heading is None:
        parent = node.getparent()
        if parent is not None:
            headings = parent.xpath("preceding::h1[1]|preceding::h2[1]|preceding::h3[1]")
            if headings:
                heading = _WS.sub(" ", headings[-1].text_content()).strip()[:200] or None
    return caption, heading


def _score(df: pd.DataFrame) -> float:
    rows, cols = df.shape
    if rows == 0 or cols == 0:
        return 0.0
    score = 0.45
    if rows >= 3:
        score += 0.15
    if rows >= 10:
        score += 0.1
    if cols >= 2:
        score += 0.1
    if cols >= 4:
        score += 0.05
    named = sum(1 for c in df.columns if not str(c).lower().startswith(("column_", "unnamed")))
    score += 0.15 * (named / max(cols, 1))
    density = float(df.notna().to_numpy().mean()) if rows else 0.0
    score += 0.1 * density
    if rows == 1:
        score -= 0.2
    return max(0.0, min(score, 0.99))


def detect_tables(html: str, base_url: str | None = None) -> tuple[list[TableCandidate], list[pd.DataFrame]]:
    """Return table metadata plus the parsed frames, aligned by index."""
    frames: list[pd.DataFrame] = []
    try:
        frames = [
            _clean_frame(df)
            for df in pd.read_html(io.StringIO(html), flavor="lxml")
            if df is not None and not df.empty
        ]
    except Exception:
        frames = []

    contexts: list[tuple[str | None, str | None]] = []
    try:
        tree = lxml_html.fromstring(html)
        table_nodes = tree.xpath("//table")
        contexts = [_context_for(node) for node in table_nodes]
        if not frames and table_nodes:
            frames = _dom_tables(table_nodes)
    except Exception:
        contexts = []

    candidates: list[TableCandidate] = []
    for index, df in enumerate(frames):
        caption, heading = contexts[index] if index < len(contexts) else (None, None)
        score = _score(df)
        candidates.append(
            TableCandidate(
                index=index,
                rows=int(df.shape[0]),
                columns=int(df.shape[1]),
                column_names=[str(c) for c in df.columns][:40],
                caption=caption,
                preceding_heading=heading,
                score=score,
                confidence=Confidence.from_score(score),
            )
        )
    return candidates, frames


def _dom_tables(table_nodes) -> list[pd.DataFrame]:
    """Fallback parser for tables pandas would not accept."""
    frames: list[pd.DataFrame] = []
    for node in table_nodes:
        rows: list[list[str]] = []
        for tr in node.xpath(".//tr"):
            cells = [
                _WS.sub(" ", cell.text_content()).strip()
                for cell in tr.xpath("./th|./td")
            ]
            if cells:
                rows.append(cells)
        if len(rows) < 2:
            continue
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        header, body = rows[0], rows[1:]
        if not any(header) or len(set(header)) < max(2, width // 2):
            header = [f"column_{i}" for i in range(width)]
            body = rows
        frames.append(_clean_frame(pd.DataFrame(body, columns=header)))
    return frames
