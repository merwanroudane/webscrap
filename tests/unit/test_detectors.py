"""Detector tests: tables, repeated DOM, structured data, pagination, APIs, files."""

from __future__ import annotations

from pathlib import Path

import pytest

from scraper_app.discovery import (
    api_detector,
    file_detector,
    pagination_detector,
    repeated_patterns,
    structured_data,
    table_detector,
)
from scraper_app.models import PaginationType

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "site"
BASE = "https://example.org/page"


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ------------------------------------------------------------------------ tables
def test_table_detector_reads_headers_and_caption():
    candidates, frames = table_detector.detect_tables(read("table.html"), BASE)
    assert len(candidates) == 1
    table = candidates[0]
    assert table.rows == 8
    assert table.columns == 5
    assert table.column_names[:2] == ["Country", "Year"]
    assert table.caption == "Annual inflation rate (%)"
    assert table.score > 0.7
    assert frames[0].iloc[0]["Country"] == "Algeria"


def test_table_detector_handles_pages_without_tables():
    candidates, frames = table_detector.detect_tables(read("cards.html"), BASE)
    assert candidates == []
    assert frames == []


# --------------------------------------------------------------- repeated blocks
def test_repeated_pattern_detection_finds_cards():
    candidates = repeated_patterns.detect_repeated_patterns(read("cards.html"), BASE)
    assert candidates
    best = candidates[0]
    assert best.item_count == 5
    names = {field.name for field in best.fields}
    assert {"title", "link"} <= names
    assert best.sample_rows[0]["title"].startswith("Inflation dynamics")
    assert best.sample_rows[0]["link"].startswith("https://example.org/papers/")


def test_repeated_pattern_extraction_is_reusable():
    candidates = repeated_patterns.detect_repeated_patterns(read("cards.html"), BASE)
    best = candidates[0]
    rows = repeated_patterns.extract_rows_with_selector(
        read("cards.html"), best.selector, best.fields, BASE
    )
    assert len(rows) == 5
    assert set(rows[0]) == {field.name for field in best.fields}


def test_navigation_blocks_are_not_proposed():
    html = """
    <html><body><nav class="nav">
      <a href="/a">A</a><a href="/b">B</a><a href="/c">C</a><a href="/d">D</a>
    </nav></body></html>
    """
    assert repeated_patterns.detect_repeated_patterns(html, BASE) == []


# ------------------------------------------------------------- structured / JSON
def test_embedded_next_data_is_found():
    blobs = structured_data.extract_embedded_json(read("js_page.html"))
    assert blobs
    arrays = structured_data.find_record_arrays(blobs[0]["data"])
    assert arrays
    assert arrays[0]["count"] == 4
    assert "indicator" in arrays[0]["keys"]


def test_json_ld_extraction():
    html = """
    <html><head><script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Dataset","name":"Inflation"}
    </script></head><body></body></html>
    """
    documents = structured_data.extract_json_ld(html)
    assert documents[0]["@type"] == "Dataset"
    assert "Dataset" in structured_data.structured_types({}, documents)


def test_flatten_record_handles_nesting():
    flat = structured_data.flatten_record(
        {"a": {"b": 1}, "tags": ["x", "y"], "items": [{"c": 2}]}
    )
    assert flat["a.b"] == 1
    assert flat["tags"] == "x, y"
    assert flat["items.0.c"] == 2


# -------------------------------------------------------------------- pagination
def test_pagination_from_url_query():
    plan = pagination_detector.detect("https://example.org/list?page=2&sort=asc")
    assert plan.type is PaginationType.PAGE_NUMBER
    assert plan.param == "page"
    assert "{page}" in (plan.url_template or "")
    assert "sort=asc" in (plan.url_template or "")


def test_pagination_offset_detected():
    plan = pagination_detector.detect("https://example.org/list?offset=0&limit=100")
    assert plan.type is PaginationType.OFFSET_LIMIT
    assert plan.step == 100


def test_pagination_rel_next_detected():
    plan = pagination_detector.detect(BASE, read("cards.html"))
    assert plan.type is PaginationType.NEXT_LINK
    assert plan.url_template.endswith("/cards2.html")


def test_pagination_load_more_detected():
    html = '<html><body><button class="more-btn">Load more</button></body></html>'
    plan = pagination_detector.detect(BASE, html)
    assert plan.type is PaginationType.LOAD_MORE
    assert plan.next_selector == "button.more-btn"


def test_infinite_scroll_hint_detected():
    html = '<html><body><div data-infinite-scroll="1"></div></body></html>'
    assert pagination_detector.detect(BASE, html).type is PaginationType.INFINITE_SCROLL


def test_no_pagination_returns_none_plan():
    assert pagination_detector.detect(BASE, "<html><body>x</body></html>").type is PaginationType.NONE


# --------------------------------------------------------------------- API/files
def test_api_candidate_from_json_response():
    body = '{"meta":{"page":1},"data":[{"a":1},{"a":2},{"a":3}]}'
    candidate = api_detector.candidate_from_response("https://example.org/api/x", body)
    assert candidate is not None
    assert candidate.records_path == "data"
    assert candidate.record_count == 3
    assert candidate.sample_keys == ["a"]


def test_api_candidates_from_html_scripts():
    html = '<script>const u = "/api/indicators?page=1"; fetch(u);</script>'
    candidates = api_detector.candidates_from_html(html, "https://example.org/p")
    assert any("/api/indicators" in c.url for c in candidates)


def test_cursor_field_detection():
    assert api_detector.detect_cursor_field({"next_cursor": "abc"}) == "next_cursor"
    assert api_detector.detect_cursor_field({"meta": {"next_page_token": "t"}}) == "meta.next_page_token"
    assert api_detector.detect_cursor_field({"data": []}) is None


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://x.org/data.csv", "csv"),
        ("https://x.org/a/b.xlsx", "excel"),
        ("https://x.org/file.parquet", "parquet"),
        ("https://x.org/report.pdf", "pdf"),
        ("https://x.org/feed/", "feed"),
        ("https://x.org/page.html", None),
    ],
)
def test_file_format_from_url(url, expected):
    assert file_detector.format_from_url(url) == expected


def test_content_type_wins_over_extension():
    assert file_detector.detect_format("https://x.org/download", "text/csv") == "csv"


def test_collect_file_links_labels_documents():
    files = file_detector.collect_file_links(
        [("https://x.org/a.csv", "Data"), ("https://x.org/b.pdf", "Report"), ("https://x.org/c", "Page")]
    )
    kinds = {f["url"]: f["kind"] for f in files}
    assert kinds["https://x.org/a.csv"] == "data"
    assert kinds["https://x.org/b.pdf"] == "document"
    assert "https://x.org/c" not in kinds
