"""Agentic engine output handling (audit v0.2 sections 34-37).

The defect these cover: whatever an agent returned was passed through
``str()`` into an HTML parser. That is correct for exactly one of the four
shapes an agent actually returns. A Browser Use run that answered with JSON —
the normal outcome when a schema is requested — produced "no data detected"
even though the agent had succeeded.
"""

from __future__ import annotations

import json

import pytest

from scraper_app.engines import agent_output


# ------------------------------------------------------------------ records
def test_a_list_of_dicts_is_records():
    kind, value = agent_output.classify([{"name": "a", "price": "1"}])
    assert kind == "records"
    assert value == [{"name": "a", "price": "1"}]


@pytest.mark.parametrize("key", ["records", "data", "items", "results", "rows", "output"])
def test_a_wrapped_record_list_is_found(key):
    kind, value = agent_output.classify({key: [{"a": 1}, {"a": 2}]})
    assert kind == "records"
    assert len(value) == 2


def test_a_json_string_of_records_is_records():
    """The shipped bug: this went to an HTML parser and vanished."""
    kind, value = agent_output.classify(json.dumps([{"city": "Algiers", "pop": "3.4m"}]))
    assert kind == "records"
    assert value[0]["city"] == "Algiers"


def test_a_fenced_json_block_is_records():
    payload = '```json\n[{"a": "1"}]\n```'
    kind, value = agent_output.classify(payload)
    assert kind == "records"
    assert value == [{"a": "1"}]


def test_a_single_flat_object_is_one_record():
    kind, value = agent_output.classify({"title": "x", "year": "2026"})
    assert kind == "records"
    assert value == [{"title": "x", "year": "2026"}]


def test_a_bare_list_of_values_becomes_one_column():
    kind, value = agent_output.classify(["a", "b"])
    assert kind == "records"
    assert value == [{"value": "a"}, {"value": "b"}]


def test_a_pydantic_model_is_unwrapped():
    from pydantic import BaseModel

    class Row(BaseModel):
        name: str

    class Rows(BaseModel):
        records: list[Row]

    kind, value = agent_output.classify(Rows(records=[Row(name="a")]))
    assert kind == "records"
    assert value == [{"name": "a"}]


# --------------------------------------------------------------------- html
@pytest.mark.parametrize(
    "payload",
    [
        "<html><body><table><tr><td>1</td></tr></table></body></html>",
        "<div class='row'><span>a</span></div>",
        "<ul><li>one</li><li>two</li></ul>",
    ],
)
def test_markup_is_html(payload):
    kind, value = agent_output.classify(payload)
    assert kind == "html"
    assert value == payload


# --------------------------------------------------------------------- text
def test_prose_is_reported_as_prose_not_parsed_as_html():
    """An agent's sentence is not a dataset and must not be treated as one."""
    kind, value = agent_output.classify(
        "I found 12 products on the page. The cheapest one costs 4.99 euros."
    )
    assert kind == "text"
    assert "12 products" in value


@pytest.mark.parametrize("payload", [None, "", "   ", {}, [], "{}"])
def test_nothing_usable_is_empty(payload):
    kind, _value = agent_output.classify(payload)
    assert kind == "empty"


def test_malformed_json_is_not_silently_accepted():
    kind, _value = agent_output.classify('{"a": ')
    assert kind == "text"


# ------------------------------------------------- engine-level consequences
class _Recorder:
    """Minimal stand-in for the pieces _from_agent touches."""

    def __init__(self):
        self.records = None


def _request(**overrides):
    from scraper_app.models import ExtractionRequest

    payload = {"url": "https://example.org/data", "add_provenance_columns": False}
    payload.update(overrides)
    return ExtractionRequest(**payload)


def test_agent_records_become_rows_without_an_html_parser():
    import time

    from scraper_app.engines.agentic_engines import BrowserUseEngine

    engine = BrowserUseEngine()
    result = engine._from_agent(
        _request(),
        None,
        [{"city": "Oran", "pop": "800k"}],
        "https://example.org/data",
        time.monotonic(),
        None,
        {"agent": "browser_use"},
    )
    assert result.success
    assert result.records == [{"city": "Oran", "pop": "800k"}]
    assert result.metadata["agent_output"] == "records"


def test_agent_prose_raises_a_clear_error():
    import time

    from scraper_app.engines.agentic_engines import BrowserUseEngine
    from scraper_app.exceptions import ErrorCode, ScraperError

    engine = BrowserUseEngine()
    with pytest.raises(ScraperError) as excinfo:
        engine._from_agent(
            _request(),
            None,
            "The page shows a list of products but I could not read the table.",
            "https://example.org/data",
            time.monotonic(),
            None,
            {},
        )
    assert excinfo.value.code is ErrorCode.NO_DATA_DETECTED
    assert "prose" in str(excinfo.value).lower()


def test_provenance_column_is_added_to_agent_records():
    import time

    from scraper_app.engines.agentic_engines import BrowserUseEngine

    result = BrowserUseEngine()._from_agent(
        _request(add_provenance_columns=True),
        None,
        [{"a": "1"}],
        "https://example.org/data",
        time.monotonic(),
        None,
        {},
    )
    assert result.records[0]["_source_url"] == "https://example.org/data"


# ------------------------------------------------------- structured output
def test_browser_use_builds_an_output_model_from_the_schema():
    """Audit §35: a schema should be enforced, not merely hoped for."""
    from scraper_app.engines.agentic_engines import BrowserUseEngine
    from scraper_app.models import ExtractionSchema, FieldSpec

    schema = ExtractionSchema(fields=[FieldSpec(name="city"), FieldSpec(name="population")])
    model = BrowserUseEngine.output_model(schema)
    assert model is not None

    instance = model.model_validate({"records": [{"city": "Algiers", "population": "3m"}]})
    assert instance.records[0].city == "Algiers"


def test_browser_use_output_model_is_none_without_a_schema():
    from scraper_app.engines.agentic_engines import BrowserUseEngine

    assert BrowserUseEngine.output_model(None) is None


# ---------------------------------------------------------------- API drift
def test_skyvern_engine_version_is_configurable(monkeypatch):
    """A vendor version bump must not require editing the source (audit §37)."""
    source = (
        __import__("pathlib")
        .Path(agent_output.__file__)
        .parent.joinpath("agentic_engines.py")
        .read_text(encoding="utf-8")
    )
    assert 'os.getenv("SKYVERN_ENGINE"' in source
    assert 'os.getenv("SKYVERN_BASE_URL"' in source


def test_stagehand_tolerates_both_sdk_flavours():
    """The SDK has shipped sync and async surfaces; neither may crash it."""
    from scraper_app.engines.agentic_engines import StagehandEngine

    assert StagehandEngine._resolve("plain value") == "plain value"

    async def awaitable():
        return "async value"

    assert StagehandEngine._resolve(awaitable()) == "async value"
