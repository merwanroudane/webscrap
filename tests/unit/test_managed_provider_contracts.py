"""Managed-fetch provider contracts (audit v0.2 section 38).

Ten hosted vendors is ten request shapes that can drift without anything in
this repository changing. These tests do not prove a vendor's API is still
correct — nothing offline can — but they do pin what *this* application sends
and how it behaves when the vendor answers badly, so a change here is
deliberate rather than accidental.

Every provider must, uniformly:

* send its credential, and never in a way that bypasses the SSRF guard;
* carry the target URL through unchanged;
* turn 401/403 into API_AUTH_REQUIRED and 429 into HTTP_429_RATE_LIMIT;
* raise a typed error on timeout rather than leaking the vendor's exception;
* refuse an empty document instead of returning an empty dataset;
* keep the key out of every error message.
"""

from __future__ import annotations

import httpx
import pytest

from scraper_app.exceptions import ErrorCode, ScraperError, UrlBlocked
from scraper_app.providers import managed_fetch
from scraper_app.providers.managed_fetch import FetchRequest

KEY = "test-key-do-not-log-3141592653"
TARGET = "https://example.org/data"


def credentialled_providers():
    """Every provider that declares credentials, so the list stays current."""
    return [p for p in managed_fetch.providers() if p.descriptor.env_keys]


def provider_ids():
    return [p.id for p in credentialled_providers()]


@pytest.fixture
def configured(monkeypatch):
    """Set every provider key, so `build` and `fetch` can run."""

    def _apply(provider):
        for name in provider.descriptor.env_keys:
            monkeypatch.setenv(name, KEY)
        return provider

    return _apply


def _provider(provider_id: str):
    provider = managed_fetch.get_provider(provider_id)
    assert provider is not None, provider_id
    return provider


def _call(provider_id, configured, **request_kwargs):
    provider = configured(_provider(provider_id))
    return provider, provider.build(FetchRequest(url=TARGET, **request_kwargs))


# --------------------------------------------------------------- registration
def test_every_provider_is_registered_once():
    ids = provider_ids()
    assert len(ids) == len(set(ids))
    assert len(ids) >= 8, ids


@pytest.mark.parametrize("provider_id", provider_ids())
def test_descriptor_declares_its_credentials(provider_id):
    from scraper_app import credentials

    provider = _provider(provider_id)
    for name in provider.descriptor.env_keys:
        assert name in set(credentials.all_env_names()), name


# ------------------------------------------------------------ request shape
@pytest.mark.parametrize("provider_id", provider_ids())
def test_request_carries_the_target_url(provider_id, configured):
    _provider_obj, call = _call(provider_id, configured)
    blob = f"{call.url}{call.params}{call.json_body}"
    assert TARGET in blob, f"{provider_id} dropped the target URL"


@pytest.mark.parametrize("provider_id", provider_ids())
def test_request_carries_the_credential(provider_id, configured):
    provider_obj, call = _call(provider_id, configured)
    blob = f"{call.params}{call.headers}{call.auth}"
    assert KEY in blob, f"{provider_obj.id} sent no credential"


#: Providers whose API has no per-request rendering switch, because the vendor
#: decides it from account/zone configuration instead. Ignoring the flag is
#: correct for these — but the descriptor has to say so, which is asserted below.
_RENDERING_IS_ACCOUNT_LEVEL = {"brightdata"}


@pytest.mark.parametrize("provider_id", provider_ids())
def test_render_js_is_expressible(provider_id, configured):
    """Asking for a rendered page must change the request, not be ignored."""
    if provider_id in _RENDERING_IS_ACCOUNT_LEVEL:
        pytest.skip("rendering is configured on the vendor side; see the note test")
    _p, plain = _call(provider_id, configured, render_js=False)
    _p2, rendered = _call(provider_id, configured, render_js=True)
    assert (plain.params, plain.json_body) != (rendered.params, rendered.json_body), provider_id


@pytest.mark.parametrize("provider_id", sorted(_RENDERING_IS_ACCOUNT_LEVEL))
def test_ignoring_the_rendering_flag_is_disclosed(provider_id):
    """Silently dropping a user's choice is not acceptable; saying so is."""
    notes = _provider(provider_id).descriptor.notes.lower()
    assert "render" in notes and "not apply" in notes, (
        f"{provider_id} ignores render_js without telling the user"
    )


@pytest.mark.parametrize("provider_id", provider_ids())
def test_method_is_a_real_http_verb(provider_id, configured):
    _p, call = _call(provider_id, configured)
    assert call.method in {"GET", "POST"}, call.method


# ------------------------------------------------------------- SSRF is first
@pytest.mark.parametrize("provider_id", provider_ids())
def test_a_managed_provider_is_not_a_way_around_the_guard(provider_id, configured, monkeypatch):
    """The vendor performs the request, but our access policy still applies."""
    provider = configured(_provider(provider_id))
    with pytest.raises((UrlBlocked, ScraperError)):
        provider.fetch(FetchRequest(url="http://169.254.169.254/latest/meta-data/"))


# ------------------------------------------------------------ error handling
def _mock_transport(monkeypatch, handler):
    """Route every outgoing httpx request to `handler`."""
    real_client = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", factory)


@pytest.mark.parametrize("provider_id", provider_ids())
@pytest.mark.parametrize(
    "status,expected",
    [
        (401, ErrorCode.API_AUTH_REQUIRED),
        (403, ErrorCode.API_AUTH_REQUIRED),
        (429, ErrorCode.HTTP_429_RATE_LIMIT),
    ],
)
def test_vendor_error_statuses_are_typed(provider_id, configured, monkeypatch, status, expected):
    provider = configured(_provider(provider_id))
    _mock_transport(monkeypatch, lambda request: httpx.Response(status, text="nope"))

    with pytest.raises(ScraperError) as excinfo:
        provider.fetch(FetchRequest(url=TARGET))
    assert excinfo.value.code is expected


@pytest.mark.parametrize("provider_id", provider_ids())
def test_a_timeout_is_typed_not_leaked(provider_id, configured, monkeypatch):
    provider = configured(_provider(provider_id))

    def handler(request):
        raise httpx.ConnectTimeout("too slow", request=request)

    _mock_transport(monkeypatch, handler)
    with pytest.raises(ScraperError) as excinfo:
        provider.fetch(FetchRequest(url=TARGET))
    assert excinfo.value.code is ErrorCode.TIMEOUT


@pytest.mark.parametrize("provider_id", provider_ids())
def test_an_empty_document_is_refused(provider_id, configured, monkeypatch):
    """An empty answer must not become an empty dataset."""
    provider = configured(_provider(provider_id))
    _mock_transport(monkeypatch, lambda request: httpx.Response(200, text=""))

    with pytest.raises(ScraperError) as excinfo:
        provider.fetch(FetchRequest(url=TARGET))
    assert excinfo.value.code is ErrorCode.NO_DATA_DETECTED


@pytest.mark.parametrize("provider_id", provider_ids())
def test_no_error_message_contains_the_key(provider_id, configured, monkeypatch):
    """The most likely place for a credential to escape is an exception."""
    provider = configured(_provider(provider_id))

    for handler in (
        lambda request: httpx.Response(401),
        lambda request: httpx.Response(429),
        lambda request: httpx.Response(500),
        lambda request: httpx.Response(200, text=""),
    ):
        _mock_transport(monkeypatch, handler)
        with pytest.raises(ScraperError) as excinfo:
            provider.fetch(FetchRequest(url=TARGET))
        rendered = f"{excinfo.value} {getattr(excinfo.value, 'context', '')}"
        assert KEY not in rendered, f"{provider_id} leaked its key in an error"


# ---------------------------------------------------------------- not configured
@pytest.mark.parametrize("provider_id", provider_ids())
def test_an_unconfigured_provider_says_so(provider_id, monkeypatch):
    provider = _provider(provider_id)
    for name in provider.descriptor.env_keys:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ScraperError) as excinfo:
        provider.fetch(FetchRequest(url=TARGET))
    assert excinfo.value.code in {
        ErrorCode.API_KEY_MISSING,
        ErrorCode.OPTIONAL_ENGINE_NOT_INSTALLED,
    }
