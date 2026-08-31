"""Provider and adapter contract tests (audit sections AM and AN).

Every external provider is exercised against a mocked transport: request
mapping in, response normalization out, typed failures, and configuration
states. No test here needs a live API, a paid call or a credential.
"""

from __future__ import annotations

import os

import httpx
import pytest

from scraper_app.exceptions import ErrorCode, ScraperError
from scraper_app.providers import (
    discovery,
    documents,
    managed_fetch,
    remote_browser,
    semantic_content,
)
from scraper_app.providers import registry as provider_registry
from scraper_app.providers.base import ProviderStatus


@pytest.fixture
def no_keys(monkeypatch):
    """Guarantee a clean, unconfigured environment."""
    for key in list(os.environ):
        if key.endswith(("_API_KEY", "_TOKEN", "_KEY", "_PASSWORD", "_USERNAME", "_PROJECT_ID")):
            monkeypatch.delenv(key, raising=False)
    return monkeypatch


# --------------------------------------------------------------- registry rules
def test_every_provider_reports_a_known_state(no_keys):
    for descriptor in provider_registry.all_descriptors():
        state = descriptor.state()
        assert isinstance(state.status, ProviderStatus)
        assert state.detail, f"{descriptor.id} gave no reason for its state"


def test_nothing_is_ready_without_credentials(no_keys):
    for descriptor in provider_registry.all_descriptors():
        if descriptor.env_keys:
            assert descriptor.state().status is not ProviderStatus.READY, descriptor.id


def test_provider_rows_are_renderable(no_keys):
    rows = provider_registry.provider_rows()
    assert rows
    required = {"id", "provider", "category", "status", "detail", "cost", "where", "setup", "docs"}
    for row in rows:
        assert required <= set(row), row


def test_configured_summary_is_all_none_without_keys(no_keys):
    summary = provider_registry.configured_summary()
    assert set(summary) == {
        "ai_provider",
        "remote_browser",
        "managed_fetch",
        "discovery",
        "semantic_content",
        "document_extractor",
    }
    assert summary["remote_browser"] is None
    assert summary["managed_fetch"] is None


# ----------------------------------------------------------------- managed fetch
def mock_httpx(monkeypatch, handler) -> None:
    """Route every ``httpx.Client`` through a MockTransport.

    The real class is captured before patching so the replacement cannot
    recurse into itself when an adapter constructs its client.
    """
    real_client = httpx.Client

    def factory(**kwargs):
        kwargs.pop("transport", None)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "Client", factory)


@pytest.mark.parametrize(
    "provider_id,env",
    [
        ("zenrows", {"ZENROWS_API_KEY": "k"}),
        ("scrapingbee", {"SCRAPINGBEE_API_KEY": "k"}),
        ("scraperapi", {"SCRAPERAPI_KEY": "k"}),
        ("scrapingant", {"SCRAPINGANT_API_KEY": "k"}),
        ("brightdata", {"BRIGHTDATA_API_TOKEN": "k"}),
    ],
)
def test_html_providers_return_the_page(monkeypatch, provider_id, env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content.decode("utf-8", errors="replace")
        return httpx.Response(
            200,
            text="<html><body><table><tr><th>a</th></tr><tr><td>1</td></tr></table></body></html>",
        )

    mock_httpx(monkeypatch, handler)

    provider = managed_fetch.get_provider(provider_id)
    assert provider is not None and provider.available()
    result = provider.fetch(managed_fetch.FetchRequest(url="https://example.org/data"))
    assert "<table>" in result.html
    assert result.provider == provider_id
    # The target URL must reach the vendor, whether in the query or the body.
    assert "example.org" in f"{captured['url']}{captured.get('body', '')}"


def test_json_provider_is_normalized(monkeypatch):
    monkeypatch.setenv("SCRAPFLY_API_KEY", "k")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"result": {"content": "<html><p>ok</p></html>"}},
            headers={"content-type": "application/json"},
        )

    mock_httpx(monkeypatch, handler)
    provider = managed_fetch.get_provider("scrapfly")
    result = provider.fetch(managed_fetch.FetchRequest(url="https://example.org/x"))
    assert result.html == "<html><p>ok</p></html>"


def test_managed_fetch_maps_auth_failure(monkeypatch):
    monkeypatch.setenv("ZENROWS_API_KEY", "k")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorised")

    mock_httpx(monkeypatch, handler)
    provider = managed_fetch.get_provider("zenrows")
    with pytest.raises(ScraperError) as info:
        provider.fetch(managed_fetch.FetchRequest(url="https://example.org/x"))
    assert info.value.code is ErrorCode.API_AUTH_REQUIRED


def test_managed_fetch_still_applies_the_url_guard(monkeypatch):
    """Routing through a vendor must not bypass our own access policy."""
    monkeypatch.setenv("ZENROWS_API_KEY", "k")
    from scraper_app.config import SecurityPolicy, Settings
    from scraper_app.security import url_guard

    # SETTINGS is frozen, so swap the whole object for a strict one.
    monkeypatch.setattr(
        url_guard, "SETTINGS", Settings(security=SecurityPolicy(allow_private_networks=False))
    )
    provider = managed_fetch.get_provider("zenrows")
    with pytest.raises(ScraperError) as info:
        provider.fetch(managed_fetch.FetchRequest(url="http://169.254.169.254/latest/meta-data/"))
    assert info.value.code is ErrorCode.URL_PRIVATE_NETWORK_BLOCKED


def test_unconfigured_provider_raises_key_missing(no_keys):
    provider = managed_fetch.get_provider("zenrows")
    with pytest.raises(ScraperError) as info:
        provider.fetch(managed_fetch.FetchRequest(url="https://example.org/x"))
    assert info.value.code is ErrorCode.API_KEY_MISSING


# --------------------------------------------------------------- remote browsers
def test_browserbase_session_returns_a_cdp_url(monkeypatch):
    monkeypatch.setenv("BROWSERBASE_API_KEY", "bb-key")
    monkeypatch.setenv("BROWSERBASE_PROJECT_ID", "proj")

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["api_key"] = request.headers.get("x-bb-api-key")
        return httpx.Response(
            201, json={"id": "sess-1", "connectUrl": "wss://connect.browserbase.com/sess-1"}
        )

    mock_httpx(monkeypatch, handler)
    provider = remote_browser.get_provider("browserbase")
    assert provider.available()
    session = provider.create_session()
    assert session.cdp_url.startswith("wss://")
    assert seen["api_key"] == "bb-key"
    assert "api.browserbase.com" in str(seen["url"])


def test_browserless_needs_no_control_plane(monkeypatch):
    monkeypatch.setenv("BROWSERLESS_TOKEN", "tok")
    provider = remote_browser.get_provider("browserless")
    session = provider.create_session()
    assert session.cdp_url.startswith("wss://") and "token=tok" in session.cdp_url


def test_remote_browser_reports_failures(monkeypatch):
    monkeypatch.setenv("HYPERBROWSER_API_KEY", "k")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    mock_httpx(monkeypatch, handler)
    provider = remote_browser.get_provider("hyperbrowser")
    with pytest.raises(ScraperError):
        provider.create_session()


def test_no_remote_browser_configured_means_local(no_keys):
    assert remote_browser.configured_provider() is None


# -------------------------------------------------------------------- discovery
def _offline_guard(monkeypatch):
    """Keep the loopback/private rejection without needing DNS."""
    monkeypatch.setattr(
        discovery,
        "is_allowed",
        lambda url: (
            not url.startswith(
                (
                    "http://127.",
                    "http://10.",
                    "http://192.168.",
                    "http://localhost",
                    "http://169.254.",
                )
            )
        ),
    )


def test_tavily_results_are_normalized(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tv")
    _offline_guard(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("authorization") == "Bearer tv"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Inflation statistics",
                        "url": "https://example.org/inflation",
                        "content": "annual inflation by country",
                        "score": 0.91,
                    },
                    {"title": "blocked", "url": "http://127.0.0.1/secret", "content": ""},
                ]
            },
        )

    mock_httpx(monkeypatch, handler)
    provider = discovery.get_provider("tavily")
    results = provider.search(discovery.DiscoveryQuery(query="inflation", max_results=5))

    # The loopback result is dropped by the URL guard, not shown to the user.
    assert len(results) == 1
    assert results[0].domain == "example.org"
    assert results[0].score == 0.91


def test_exa_results_are_normalized(monkeypatch):
    monkeypatch.setenv("EXA_API_KEY", "ex")
    _offline_guard(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("x-api-key") == "ex"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "GDP tables",
                        "url": "https://data.example.org/gdp",
                        "text": "gross domestic product",
                        "publishedDate": "2026-01-01",
                    }
                ]
            },
        )

    mock_httpx(monkeypatch, handler)
    provider = discovery.get_provider("exa")
    results = provider.search(discovery.DiscoveryQuery(query="gdp"))
    assert results[0].published == "2026-01-01"


def test_discovery_without_keys_returns_guidance(no_keys):
    from scraper_app.discovery import source_finder

    outcome = source_finder.find_sources("inflation")
    assert outcome.candidates == []
    assert outcome.warnings
    assert "no source discovery provider is configured" in outcome.warnings[0].lower()


# ------------------------------------------------------------- semantic content
def test_diffbot_document_is_normalized(monkeypatch):
    monkeypatch.setenv("DIFFBOT_TOKEN", "dt")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "objects": [
                    {
                        "pageUrl": "https://example.org/article",
                        "title": "Central bank holds rates",
                        "text": "The central bank kept its policy rate unchanged.",
                        "author": "Newsroom",
                        "date": "2026-08-20",
                        "type": "article",
                    }
                ]
            },
            headers={"content-type": "application/json"},
        )

    mock_httpx(monkeypatch, handler)
    provider = semantic_content.get_provider("diffbot")
    document = provider.read("https://example.org/article")
    record = document.as_record()
    assert record["title"].startswith("Central bank")
    assert record["text_chars"] > 10


def test_semantic_provider_reports_empty_pages(monkeypatch):
    monkeypatch.setenv("DIFFBOT_TOKEN", "dt")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"objects": []}, headers={"content-type": "application/json"}
        )

    mock_httpx(monkeypatch, handler)
    provider = semantic_content.get_provider("diffbot")
    with pytest.raises(ScraperError) as info:
        provider.read("https://example.org/empty")
    assert info.value.code is ErrorCode.NO_DATA_DETECTED


# -------------------------------------------------------------------- documents
def test_document_extractor_selection_is_honest():
    extractor = documents.best_extractor()
    if extractor is None:
        # Neither PyMuPDF nor Docling installed: both must explain themselves.
        for provider in documents.providers():
            assert not provider.available()
            assert provider.state().detail
    else:
        assert extractor.id in {"pymupdf", "docling"}


def test_document_result_turns_tables_into_rows():
    result = documents.DocumentResult(
        url="https://example.org/report.pdf",
        pages=[
            documents.DocumentPage(
                number=1,
                tables=[[["country", "value"], ["Algeria", "9.3"], ["Morocco", "6.1"]]],
            ),
            documents.DocumentPage(number=2, text="Notes about the table."),
        ],
        extractor="pymupdf",
    )
    records = result.to_records()
    assert len(records) == 3
    assert records[0] == {"country": "Algeria", "value": "9.3", "_page": 1, "_table": 1}
    assert records[-1]["page"] == 2
    assert result.table_count == 1
