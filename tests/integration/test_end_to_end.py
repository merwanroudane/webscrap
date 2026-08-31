"""End-to-end acceptance scenarios A-G (spec section 67).

All scenarios run against the bundled fixture server: no live website is
touched, so results are deterministic.
"""

from __future__ import annotations

import pytest

from scraper_app import service
from scraper_app.data.cleaner import CleaningOptions
from scraper_app.exceptions import ErrorCode, ScraperError
from scraper_app.models import ExtractionRequest, PaginationType


def _request(url: str, **kwargs) -> ExtractionRequest:
    kwargs.setdefault("max_pages", 1)
    return ExtractionRequest(url=url, **kwargs)


# ---------------------------------------------------------------- Scenario A
def test_scenario_a_static_table_to_dataset(server):
    analysis = service.analyze(server.url("/table.html"), user_goal="country, year, inflation")
    profile = analysis.profile

    assert profile.robots.state == "allowed"
    assert profile.table_count == 1
    candidate = profile.candidates[0]
    assert candidate.engine == "table"
    assert candidate.rows_estimate == 8

    outcome = service.extract(
        _request(server.url("/table.html")),
        candidate,
        profile=profile,
        schema=analysis.schema,
        logger=analysis.logger,
        run_id=analysis.run_id,
    )
    assert outcome.result.engine == "table"
    assert len(outcome.clean_df) == 8
    assert {"country", "year", "inflation"} <= set(outcome.clean_df.columns)
    assert outcome.mapping is not None and outcome.mapping.unmatched == []
    assert "_source_url" in outcome.clean_df.columns
    assert outcome.decision.uses_ai is False
    assert outcome.decision.uses_cloud is False


# ---------------------------------------------------------------- Scenario B
def test_scenario_b_repeated_cards_with_pagination(server):
    analysis = service.analyze(server.url("/cards.html"))
    profile = analysis.profile
    assert profile.pagination.type is PaginationType.NEXT_LINK

    candidate = next(c for c in profile.candidates if c.engine == "repeated_dom")
    assert candidate.rows_estimate == 5
    assert {"title", "link"} <= set(candidate.columns)

    outcome = service.extract(
        _request(server.url("/cards.html"), max_pages=2, pagination=profile.pagination),
        candidate,
        profile=profile,
        logger=analysis.logger,
        run_id=analysis.run_id,
    )
    assert outcome.result.pages_successful == 2
    assert len(outcome.clean_df) == 10
    assert outcome.clean_df["_source_page"].nunique() == 2


# ---------------------------------------------------------------- Scenario C
def test_scenario_c_js_page_switches_to_observed_json_api(server):
    """The static HTML references a JSON endpoint, so the router uses HTTPX, not a browser."""
    analysis = service.analyze(server.url("/js_page.html"))
    profile = analysis.profile

    assert profile.requires_js is True
    assert profile.api_candidates, "the endpoint referenced in the page should be detected"

    candidate = profile.candidates[0]
    assert candidate.engine == "json_api"

    outcome = service.extract(
        _request(server.url("/js_page.html")),
        candidate,
        profile=profile,
        logger=analysis.logger,
        run_id=analysis.run_id,
    )
    assert outcome.result.engine == "json_api"
    assert outcome.decision.uses_browser is False
    assert len(outcome.clean_df) == 3
    assert {"country", "year", "value"} <= set(outcome.clean_df.columns)


# ---------------------------------------------------------------- Scenario C2
def test_json_api_pagination_stops_on_empty_page(server):
    analysis = service.analyze(server.url("/api/indicators?page=1"))
    profile = analysis.profile
    assert profile.pagination.type is PaginationType.PAGE_NUMBER

    outcome = service.extract(
        _request(server.url("/api/indicators?page=1"), max_pages=5, pagination=profile.pagination),
        profile.candidates[0],
        profile=profile,
        logger=analysis.logger,
        run_id=analysis.run_id,
    )
    assert len(outcome.clean_df) == 6  # the fixture has six records over two pages
    assert outcome.result.pages_requested == 3  # third page returns an empty list and stops


# ---------------------------------------------------------------- Scenario D
def test_direct_csv_file_is_downloaded(server):
    analysis = service.analyze(server.url("/data/indicators.csv"))
    profile = analysis.profile
    assert profile.is_file and profile.file_format == "csv"

    outcome = service.extract(
        _request(server.url("/data/indicators.csv")),
        profile.candidates[0],
        profile=profile,
        logger=analysis.logger,
        run_id=analysis.run_id,
    )
    assert outcome.result.engine == "direct_file"
    assert len(outcome.clean_df) == 3


# ---------------------------------------------------------------- Scenario E
def test_scenario_e_natural_language_fields_are_mapped(server):
    analysis = service.analyze(
        server.url("/table.html"),
        user_goal="Extract country, year, inflation rate and unemployment",
    )
    assert analysis.schema is not None
    names = analysis.schema.field_names()
    assert {"country", "year", "inflation", "unemployment"} <= set(names)

    outcome = service.extract(
        _request(server.url("/table.html")),
        analysis.profile.candidates[0],
        profile=analysis.profile,
        schema=analysis.schema,
        logger=analysis.logger,
        run_id=analysis.run_id,
    )
    matched = {m.requested: m.matched_column for m in outcome.mapping.mappings}
    assert matched["unemployment"] == "Unemployment"
    assert outcome.clean_df.columns[0] == "country"


# ---------------------------------------------------------------- Scenario F
def test_scenario_f_research_artifacts_are_produced(server):
    analysis = service.analyze(server.url("/table.html"))
    outcome = service.extract(
        _request(server.url("/table.html")),
        analysis.profile.candidates[0],
        profile=analysis.profile,
        logger=analysis.logger,
        run_id=analysis.run_id,
    )
    outcome = service.apply_cleaning(
        outcome, CleaningOptions(numeric_conversion=True, parse_percentages=True)
    )

    assert outcome.provenance.rows_raw == 8
    assert outcome.provenance.robots_status == "allowed"
    assert outcome.provenance.recipe_hash
    assert outcome.provenance.cleaning_operations

    dictionary = outcome.dictionary
    assert {"variable", "dtype", "missing_pct", "name_source"} <= set(dictionary.columns)

    assert "httpx" in outcome.script and "pandas" in outcome.script
    assert "Authorization" not in outcome.script

    bundle = service.build_bundle(outcome)
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        names = set(archive.namelist())
    assert {
        "dataset_clean.csv",
        "dataset_raw.csv",
        "data_dictionary.csv",
        "provenance.json",
        "extraction_recipe.json",
        "extraction_recipe.yaml",
        "generated_scraper.py",
        "README_reproduction.md",
        "CITATION.txt",
    } <= names


# ---------------------------------------------------------------- Scenario G
def test_scenario_g_failures_are_typed_and_safe(server):
    with pytest.raises(ScraperError) as info:
        service.analyze("http://169.254.169.254/latest/meta-data/")
    assert info.value.code is ErrorCode.URL_PRIVATE_NETWORK_BLOCKED
    assert info.value.message("en")
    assert info.value.actions("ar")

    with pytest.raises(ScraperError) as missing:
        service.analyze(server.url("/does-not-exist.html"))
    assert missing.value.code is ErrorCode.HTTP_404


def test_article_extraction(server):
    analysis = service.analyze(server.url("/article.html"))
    candidate = next(c for c in analysis.profile.candidates if c.engine == "article")
    outcome = service.extract(
        _request(server.url("/article.html")),
        candidate,
        profile=analysis.profile,
        logger=analysis.logger,
        run_id=analysis.run_id,
    )
    assert len(outcome.clean_df) == 1
    assert outcome.clean_df.iloc[0]["title"].startswith("Central bank")
    assert outcome.clean_df.iloc[0]["text_chars"] > 300


def test_cleaning_is_reversible(server):
    analysis = service.analyze(server.url("/table.html"))
    outcome = service.extract(
        _request(server.url("/table.html")),
        analysis.profile.candidates[0],
        profile=analysis.profile,
        logger=analysis.logger,
        run_id=analysis.run_id,
    )
    original = outcome.clean_df.copy()
    outcome = service.apply_cleaning(
        outcome, CleaningOptions(numeric_conversion=True, parse_percentages=True)
    )
    assert outcome.clean_df["Inflation"].dtype.kind == "f"

    outcome = service.reset_cleaning(outcome)
    assert list(outcome.clean_df.columns) == list(original.columns)
    assert outcome.clean_df["Inflation"].iloc[0] == original["Inflation"].iloc[0]
    assert outcome.provenance.cleaning_operations == []


def test_history_persist_and_reload(server, tmp_path):
    analysis = service.analyze(server.url("/table.html"))
    outcome = service.extract(
        _request(server.url("/table.html")),
        analysis.profile.candidates[0],
        profile=analysis.profile,
        logger=analysis.logger,
        run_id=analysis.run_id,
    )
    record = service.persist(outcome)
    from scraper_app.storage import run_store

    assert record.rows == 8
    reloaded = run_store.load_frame(record.run_id)
    assert reloaded is not None and len(reloaded) == 8
    assert run_store.load_recipe(record.run_id)["engine"] == "table"
    assert any(r.run_id == record.run_id for r in run_store.list_runs())
