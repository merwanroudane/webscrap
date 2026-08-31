"""Regression tests for the v0.2 runtime defects (audit sections 26-46).

Each test below corresponds to a bug that would have reached a user:

* an async engine crashing the moment it ran inside an event loop;
* Scrapy working once per process and raising ``ReactorNotRestartable`` after;
* LiteLLM reporting "Ready" and then failing to authenticate;
* a 200-page PDF whose every word was attributed to page 1;
* a provenance manifest that could not say which vendor saw the query;
* two dependency manifests that were free to disagree.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from scraper_app.async_runner import run_async_safely

ROOT = Path(__file__).resolve().parents[2]


# ------------------------------------------------------- async engine plumbing
async def _work(value: int = 7) -> int:
    await asyncio.sleep(0)
    return value


def test_run_async_safely_without_a_running_loop():
    assert run_async_safely(_work) == 7


def test_run_async_safely_inside_a_running_loop():
    """asyncio.run() raises here; the whole point of the helper."""

    async def caller() -> int:
        return run_async_safely(_work)

    assert asyncio.run(caller()) == 7


def test_run_async_safely_accepts_a_coroutine_too():
    assert run_async_safely(_work()) == 7


def test_run_async_safely_propagates_engine_errors():
    async def boom() -> None:
        raise ValueError("engine failed")

    async def caller() -> None:
        run_async_safely(boom)

    with pytest.raises(ValueError, match="engine failed"):
        asyncio.run(caller())


def test_no_engine_calls_asyncio_run_directly():
    """asyncio.run in an engine is the bug; run_async_safely is the fix."""
    offenders = []
    for path in (ROOT / "src" / "scraper_app" / "engines").glob("*.py"):
        if re.search(r"^\s*(?!#).*asyncio\.run\(", path.read_text(encoding="utf-8"), re.M):
            offenders.append(path.name)
    assert not offenders, f"these engines still call asyncio.run directly: {offenders}"


# ------------------------------------------------------------ Scrapy lifecycle
def test_scrapy_engine_does_not_start_a_reactor_in_process():
    """A Twisted reactor cannot restart, so the crawl must leave this process."""
    source = (ROOT / "src" / "scraper_app" / "engines" / "crawler_engines.py").read_text(
        encoding="utf-8"
    )
    scrapy_section = source[
        source.index("class ScrapyEngine") : source.index("class CrawleeEngine")
    ]
    assert "CrawlerProcess" not in scrapy_section, (
        "ScrapyEngine must not run CrawlerProcess in the application process; "
        "the second extraction in a session would raise ReactorNotRestartable."
    )
    assert "subprocess.run" in scrapy_section


def test_scrapy_worker_is_standalone():
    """The subprocess must not need the application on its import path."""
    worker = ROOT / "src" / "scraper_app" / "engines" / "_scrapy_worker.py"
    text = worker.read_text(encoding="utf-8")
    assert "scraper_app" not in text.replace("``scraper_app``", "")
    # It must at least parse under the interpreter that will run it.
    compile(text, str(worker), "exec")


def test_scrapy_worker_reports_failure_instead_of_hanging(tmp_path):
    """No Scrapy installed here: the worker must still write a result file."""
    config = tmp_path / "config.json"
    output = tmp_path / "pages.json"
    config.write_text(
        json.dumps({"urls": ["http://127.0.0.1/x"], "output": str(output), "settings": {}}),
        encoding="utf-8",
    )
    worker = ROOT / "src" / "scraper_app" / "engines" / "_scrapy_worker.py"
    subprocess.run([sys.executable, str(worker), str(config)], capture_output=True, timeout=120)

    assert output.exists(), "the worker must always produce an output file"
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert "pages" in payload and "error" in payload


# --------------------------------------------------------------------- LiteLLM
def _litellm_env(monkeypatch, **values):
    for name in (
        "SRWS_LITELLM_MODEL",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_litellm_default_matches_the_key_that_is_present(monkeypatch):
    """The shipped bug: only an Anthropic key, yet it tried gpt-4o-mini."""
    from scraper_app.ai.providers import litellm_provider

    _litellm_env(monkeypatch, ANTHROPIC_API_KEY="test-key")
    model = litellm_provider.resolve_model()
    assert model.startswith("anthropic/"), model
    assert "OPENAI_API_KEY" not in litellm_provider.keys_for_model(model)


@pytest.mark.parametrize(
    "env,prefix",
    [
        ({"OPENAI_API_KEY": "k"}, ""),
        ({"ANTHROPIC_API_KEY": "k"}, "anthropic"),
        ({"GEMINI_API_KEY": "k"}, "gemini"),
        ({"GOOGLE_API_KEY": "k"}, "gemini"),
    ],
)
def test_litellm_backend_always_has_its_key(monkeypatch, env, prefix):
    from scraper_app.ai.providers import litellm_provider

    _litellm_env(monkeypatch, **env)
    model = litellm_provider.resolve_model()
    assert litellm_provider.backend_of(model) == prefix
    needed = litellm_provider.keys_for_model(model)
    assert any(name in env for name in needed), (needed, env)


def test_litellm_explicit_model_is_respected(monkeypatch):
    from scraper_app.ai.providers import litellm_provider

    _litellm_env(monkeypatch, SRWS_LITELLM_MODEL="groq/llama-3.1-70b", ANTHROPIC_API_KEY="k")
    assert litellm_provider.resolve_model() == "groq/llama-3.1-70b"


def test_litellm_is_not_ready_without_the_matching_key(monkeypatch):
    from scraper_app.ai.providers import litellm_provider

    _litellm_env(monkeypatch, SRWS_LITELLM_MODEL="gpt-4o-mini", ANTHROPIC_API_KEY="k")
    monkeypatch.setattr(litellm_provider, "__import__", __import__, raising=False)
    # Pretend the package is installed so we exercise the credential branch.
    monkeypatch.setitem(sys.modules, "litellm", type(sys)("litellm"))

    availability = litellm_provider.LiteLLMProvider().availability()
    assert not availability.ready
    assert "gpt-4o-mini" in availability.reason


def test_litellm_registry_entry_agrees_with_the_provider(monkeypatch):
    """Audit §27: two registries must not disagree about the same provider."""
    from scraper_app.ai.providers.litellm_provider import LiteLLMProvider
    from scraper_app.providers import registry

    _litellm_env(monkeypatch, SRWS_LITELLM_MODEL="gpt-4o-mini", ANTHROPIC_API_KEY="k")
    monkeypatch.setitem(sys.modules, "litellm", type(sys)("litellm"))

    descriptor = next(d for d in registry.all_descriptors() if d.id == "litellm")
    assert descriptor.state().ready is LiteLLMProvider().availability().ready


# ------------------------------------------------------------------- documents
class _Prov:
    def __init__(self, page_no: int) -> None:
        self.page_no = page_no


class _Text:
    def __init__(self, text: str, page: int) -> None:
        self.text = text
        self.prov = [_Prov(page)]


class _FakeDocument:
    """Stands in for a converted Docling document."""

    tables: list = []

    def __init__(self) -> None:
        self.texts = [_Text("first page body", 1), _Text("page seven body", 7)]

    def export_to_markdown(self) -> str:
        return "first page body\n\npage seven body"


def test_docling_attributes_text_to_its_real_page():
    """The bug: an entire multi-page PDF was recorded as page 1."""
    from scraper_app.providers.documents import DoclingExtractor

    result = DoclingExtractor()._to_pages(_FakeDocument(), url="x", max_pages=None)
    by_number = {page.number: page.text for page in result.pages}

    assert set(by_number) == {1, 7}
    assert "page seven body" in by_number[7]
    assert "page seven body" not in by_number[1]


def test_docling_max_pages_limits_real_pages():
    from scraper_app.providers.documents import DoclingExtractor

    result = DoclingExtractor()._to_pages(_FakeDocument(), url="x", max_pages=3)
    assert [page.number for page in result.pages] == [1]
    assert result.metadata["pages_limited_to"] == 3


def test_docling_says_so_when_it_cannot_attribute_pages():
    """A whole-document fallback must be labelled, not silently called page 1."""
    from scraper_app.providers.documents import DoclingExtractor

    class NoProvenance(_FakeDocument):
        def __init__(self) -> None:
            self.texts = []

    result = DoclingExtractor()._to_pages(NoProvenance(), url="x", max_pages=None)
    assert "page_attribution" in result.metadata


# ------------------------------------------------------------------ provenance
def test_provenance_names_the_vendor_and_model():
    """Audit §60: 'engine' alone cannot answer who saw the query."""
    from scraper_app.data import provenance
    from scraper_app.models import ExtractionResult

    result = ExtractionResult(
        success=True,
        engine="managed_fetch",
        columns=["a"],
        rows=1,
        metadata={"provider": "zenrows", "ai_provider": "anthropic", "ai_model": "claude-sonnet-5"},
    )
    manifest = provenance.build(
        run_id="r1",
        request_url="https://example.org/data",
        profile=None,
        result=result,
        decision=None,
        schema=None,
        rows_clean=1,
    )

    assert manifest.provider_id == "zenrows"
    assert manifest.provider_category == "managed_fetch"
    assert manifest.managed_fetch_provider == "zenrows"
    assert manifest.remote_browser_provider is None
    assert manifest.ai_provider == "anthropic"
    assert manifest.ai_model == "claude-sonnet-5"


def test_provenance_stays_empty_for_a_purely_local_run():
    from scraper_app.data import provenance
    from scraper_app.models import ExtractionResult

    result = ExtractionResult(success=True, engine="table", columns=["a"], rows=1)
    manifest = provenance.build(
        run_id="r1",
        request_url="https://example.org/data",
        profile=None,
        result=result,
        decision=None,
        schema=None,
        rows_clean=1,
    )
    assert manifest.provider_id is None
    assert manifest.ai_model is None


def test_provenance_never_carries_a_key():
    """A vendor key must not survive into the manifest, even via metadata."""
    from scraper_app.data import provenance
    from scraper_app.models import ExtractionResult

    secret = "sk-live-000111222333444555"
    result = ExtractionResult(
        success=True,
        engine="managed_fetch",
        columns=["a"],
        rows=1,
        metadata={"provider": "zenrows"},
    )
    manifest = provenance.build(
        run_id="r1",
        request_url=f"https://api.zenrows.com/v1/?apikey={secret}&url=https://example.org",
        profile=None,
        result=result,
        decision=None,
        schema=None,
        rows_clean=1,
    )
    blob = provenance.to_json_bytes(manifest).decode("utf-8")
    assert secret not in blob


# ------------------------------------------------------- dependency manifests
def test_requirements_is_generated_from_the_lockfile():
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "GENERATED FILE" in text
    assert "uv.lock" in text


def test_requirements_pins_every_package():
    """Audit §44: an unpinned production manifest is not reproducible."""
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    unpinned = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.startswith((" ", "#")) and "==" not in line
    ]
    assert not unpinned, f"unpinned requirements: {unpinned}"


def test_streamlit_itself_is_pinned():
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert re.search(r"^streamlit==\d", text, re.M)


def test_citation_file_exists_and_matches_the_version():
    from scraper_app.config import APP_VERSION

    citation = ROOT / "CITATION.cff"
    assert citation.exists()
    text = citation.read_text(encoding="utf-8")
    assert f"version: {APP_VERSION}" in text
    assert "Roudane" in text
