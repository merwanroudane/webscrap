"""Export round-trips, recipe reuse, code generation and routing tests."""

from __future__ import annotations

import io
import json

import pandas as pd
import pytest

from scraper_app.exceptions import ErrorCode, ScraperError
from scraper_app.export import exporters
from scraper_app.models import (
    CandidateDataset,
    Confidence,
    DatasetKind,
    ExtractionRequest,
    ExtractionResult,
    RouteDecision,
)
from scraper_app.reproducibility import code_generator
from scraper_app.reproducibility import recipe as recipe_module
from scraper_app.routing import router
from scraper_app.routing.capability_registry import engine_instances, engine_status_table


@pytest.fixture
def frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "country": ["Algeria", "Morocco", "Tunisia"],
            "year": [2023, 2023, 2023],
            "inflation": [9.3, 6.1, 9.3],
            "note": ["a", None, "c"],
        }
    )


# ------------------------------------------------------------------- exports
@pytest.mark.parametrize("key", ["csv", "tsv", "json", "jsonl", "parquet", "feather", "xlsx"])
def test_export_round_trip(frame, key):
    payload = exporters.build(frame, key)
    assert payload

    buffer = io.BytesIO(payload)
    if key == "csv":
        restored = pd.read_csv(buffer)
    elif key == "tsv":
        restored = pd.read_csv(buffer, sep="\t")
    elif key == "json":
        restored = pd.read_json(buffer)
    elif key == "jsonl":
        restored = pd.read_json(buffer, lines=True)
    elif key == "parquet":
        restored = pd.read_parquet(buffer)
    elif key == "feather":
        restored = pd.read_feather(buffer)
    else:
        restored = pd.read_excel(buffer)

    assert list(restored.columns) == list(frame.columns)
    assert len(restored) == len(frame)
    assert restored["country"].tolist() == frame["country"].tolist()


def test_sqlite_round_trip(frame, tmp_path):
    import sqlite3

    path = tmp_path / "out.sqlite"
    path.write_bytes(exporters.build(frame, "sqlite"))
    with sqlite3.connect(path) as connection:
        restored = pd.read_sql("select * from dataset", connection)
    assert len(restored) == 3
    assert restored["inflation"].iloc[0] == pytest.approx(9.3)


def test_stata_round_trip(frame, tmp_path):
    path = tmp_path / "out.dta"
    path.write_bytes(exporters.build(frame, "dta"))
    restored = pd.read_stata(path)
    assert list(restored.columns) == list(frame.columns)
    assert len(restored) == 3


def test_stata_rejects_invalid_column_names(frame):
    bad = frame.rename(columns={"country": "country name (long)"})
    support = exporters.FORMATS_BY_KEY["dta"].check(bad)
    assert not support.ok
    assert "Stata" in support.reason
    with pytest.raises(ScraperError) as info:
        exporters.build(bad, "dta")
    assert info.value.code is ErrorCode.EXPORT_FORMAT_LIMITATION


def test_empty_dataset_is_never_exported():
    empty = pd.DataFrame()
    for fmt, support in exporters.available_formats(empty):
        assert not support.ok, fmt.key


def test_nested_values_are_flattened_for_csv():
    frame = pd.DataFrame({"a": [{"x": 1}], "b": [[1, 2]]})
    text = exporters.build(frame, "csv").decode("utf-8-sig")
    assert "{'x': 1}" in text


# ------------------------------------------------------------------- recipes
def _sample_recipe() -> dict:
    request = ExtractionRequest(url="https://example.org/data", max_pages=3)
    candidate = CandidateDataset(
        id="table_0",
        kind=DatasetKind.TABLE,
        title="Table 1",
        engine="table",
        score=0.9,
        confidence=Confidence.HIGH,
        payload={"table_index": 0},
    )
    result = ExtractionResult(success=True, engine="table", columns=["country"], rows=8)
    decision = RouteDecision(engine="table", score=0.9, rationale="HTML table")
    return recipe_module.build(
        name="inflation", request=request, candidate=candidate, result=result, decision=decision
    )


def test_recipe_round_trip_rebuilds_request_and_candidate():
    recipe = _sample_recipe()
    payload = recipe_module.to_json_bytes(recipe)

    restored = recipe_module.from_json(payload)
    request = recipe_module.to_request(restored)
    candidate = recipe_module.to_candidate(restored)

    assert request.url == "https://example.org/data"
    assert request.max_pages == 3
    assert candidate is not None
    assert candidate.kind is DatasetKind.TABLE
    assert candidate.payload["table_index"] == 0
    assert recipe_module.recipe_hash(recipe) == recipe_module.recipe_hash(restored)


def test_recipe_never_contains_credentials():
    from scraper_app.models import RequestOptions

    request = ExtractionRequest(
        url="https://example.org/data",
        options=RequestOptions(headers={"Authorization": "Bearer super-secret"}),
    )
    recipe = recipe_module.build(
        name="x",
        request=request,
        candidate=None,
        result=ExtractionResult(success=True, engine="table"),
        decision=None,
    )
    blob = json.dumps(recipe)
    assert "super-secret" not in blob
    assert recipe_module.to_yaml_bytes(recipe)


def test_recipe_yaml_is_parseable():
    import yaml

    recipe = _sample_recipe()
    restored = yaml.safe_load(recipe_module.to_yaml_bytes(recipe))
    assert restored["engine"] == "table"


# ------------------------------------------------------------- code generation
@pytest.mark.parametrize(
    "engine",
    ["json_api", "table", "repeated_dom", "direct_file", "article", "feed", "links", "playwright"],
)
def test_generated_code_is_valid_python(engine):
    recipe = _sample_recipe()
    recipe["engine"] = engine
    script = code_generator.generate(
        engine=engine, url="https://example.org/data", recipe=recipe, created="2026-08-31"
    )
    compile(script, "generated_scraper.py", "exec")
    assert "https://example.org/data" in script
    assert "api_key" not in script.lower() or "os.environ" in script


def test_generated_code_matches_engine():
    recipe = _sample_recipe()
    api_script = code_generator.generate(engine="json_api", url="https://x.org/api", recipe=recipe)
    assert "httpx" in api_script and "read_html" not in api_script

    browser_script = code_generator.generate(engine="playwright", url="https://x.org", recipe=recipe)
    assert "sync_playwright" in browser_script


# -------------------------------------------------------------------- routing
def test_registry_reports_honest_status():
    rows = {row.name: row for row in engine_status_table()}
    assert rows["table"].state == "ready"
    assert rows["scrapling"].state == "catalogue"
    assert "not implemented" in rows["scrapling"].detail.lower()


def test_router_prefers_deterministic_engine_for_a_table():
    request = ExtractionRequest(url="https://example.org/x")
    candidate = CandidateDataset(
        id="t", kind=DatasetKind.TABLE, title="Table", engine="table", score=0.9,
        confidence=Confidence.HIGH,
    )
    engine, decision = router.choose_engine(request, candidate)
    assert engine.name == "table"
    assert decision.uses_ai is False
    assert decision.uses_cloud is False
    assert "table" in decision.rationale.lower()


def test_router_refuses_cloud_when_not_allowed():
    request = ExtractionRequest(url="https://example.org/x", allow_cloud=False)
    candidate = CandidateDataset(
        id="t", kind=DatasetKind.TABLE, title="T", engine="firecrawl", score=0.95,
        confidence=Confidence.HIGH,
    )
    engine, _decision = router.choose_engine(request, candidate)
    assert engine.cost_mode != "metered"


def test_router_skips_browser_when_disabled():
    request = ExtractionRequest(url="https://example.org/x", allow_browser=False)
    candidate = CandidateDataset(
        id="t", kind=DatasetKind.REPEATED, title="T", engine="repeated_dom", score=0.8,
        confidence=Confidence.MEDIUM,
    )
    engine, _decision = router.choose_engine(request, candidate)
    assert engine.name != "playwright"


def test_optional_engines_never_raise_import_errors():
    for name, engine in engine_instances().items():
        availability = engine.availability()
        assert isinstance(availability.ready, bool), name
        if not availability.ready:
            assert availability.reason, name
