"""Managed fetch / scraping providers (audit section N).

These services fetch a page on your behalf and return its HTML. They are all
optional, all metered, and all disabled unless the researcher turns cloud
providers on *and* configures a key.

Two rules are enforced here regardless of provider:

* the **target URL still passes the SSRF guard** — routing a request through a
  vendor does not exempt it from our own access policy;
* anti-bot / CAPTCHA-solving switches are never exposed. These adapters fetch
  public pages; they are not a way around access controls.

One request builder and one response normalizer per provider, sharing a single
HTTP implementation, so ten vendors do not mean ten copies of the same code.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..config import SETTINGS
from ..exceptions import ErrorCode, ScraperError, http_status_code
from ..security.url_guard import guard_url
from .base import BaseProvider, ProviderCategory, ProviderDescriptor


@dataclass
class FetchRequest:
    """What the caller wants fetched."""

    url: str
    render_js: bool = False
    country: str | None = None
    timeout: float = 60.0


@dataclass
class FetchResult:
    """Normalized provider response."""

    url: str
    status_code: int
    html: str
    provider: str
    cost_note: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderCall:
    """A provider-specific HTTP call, built from a :class:`FetchRequest`."""

    method: str
    url: str
    params: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    json_body: dict[str, Any] | None = None
    auth: tuple[str, str] | None = None


class ManagedFetchProvider(BaseProvider):
    """Fetch a public page through a managed service."""

    #: Builds the vendor call. Set by subclasses.
    build: Callable[[ManagedFetchProvider, FetchRequest], ProviderCall]
    #: Turns the vendor response into HTML. Set by subclasses.
    normalize: Callable[[ManagedFetchProvider, Any], str]

    def describe(self) -> dict[str, Any]:
        return self.descriptor.as_row()

    def key(self) -> str:
        for name in self.descriptor.env_keys:
            value = os.getenv(name, "").strip()
            if value:
                return value
        return ""

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Fetch one page. Raises typed errors; never leaks the key."""
        import httpx

        self._require_ready()

        # The guard applies to the *target*, even though the vendor performs the
        # request. A managed provider is not a way around our access policy.
        guarded = guard_url(request.url)
        request = FetchRequest(
            url=guarded.url,
            render_js=request.render_js,
            country=request.country,
            timeout=request.timeout,
        )

        call = self.build(request)  # type: ignore[misc]
        try:
            with httpx.Client(timeout=request.timeout, follow_redirects=True) as client:
                response = client.request(
                    call.method,
                    call.url,
                    params=call.params or None,
                    headers={"User-Agent": SETTINGS.user_agent, **call.headers},
                    json=call.json_body,
                    auth=call.auth,
                )
        except httpx.TimeoutException as exc:
            raise ScraperError(ErrorCode.TIMEOUT, f"{self.label} timed out.") from exc
        except httpx.HTTPError as exc:
            raise ScraperError(
                ErrorCode.CONNECTION_ERROR,
                f"{self.label} could not be reached ({exc.__class__.__name__}).",
            ) from exc

        if response.status_code in {401, 403}:
            raise ScraperError(
                ErrorCode.API_AUTH_REQUIRED,
                f"{self.label} rejected the credentials configured for it.",
            )
        if response.status_code == 429:
            raise ScraperError(ErrorCode.HTTP_429_RATE_LIMIT, f"{self.label} rate limit reached.")
        if response.status_code >= 400:
            raise ScraperError(
                http_status_code(response.status_code),
                f"{self.label} returned {response.status_code}.",
            )

        payload: Any = response.text
        content_type = (response.headers.get("content-type") or "").lower()
        if "json" in content_type:
            try:
                payload = response.json()
            except Exception:
                payload = response.text

        html = self.normalize(payload)  # type: ignore[misc]
        if not html:
            raise ScraperError(
                ErrorCode.NO_DATA_DETECTED, f"{self.label} returned an empty document."
            )

        return FetchResult(
            url=guarded.url,
            status_code=response.status_code,
            html=html,
            provider=self.id,
            cost_note=f"One metered request to {self.label}.",
            raw=payload if isinstance(payload, dict) else {},
        )


def _text(payload: Any) -> str:
    return payload if isinstance(payload, str) else ""


def _make(
    provider_id: str,
    label: str,
    env_keys: tuple[str, ...],
    docs: str,
    build: Callable[[ManagedFetchProvider, FetchRequest], ProviderCall],
    normalize: Callable[[ManagedFetchProvider, Any], str] = lambda self, payload: _text(payload),
    notes: str = "",
) -> type[ManagedFetchProvider]:
    """Create a provider class from its request/response contract."""

    descriptor = ProviderDescriptor(
        id=provider_id,
        label=label,
        category=ProviderCategory.MANAGED_FETCH,
        cost_mode="metered",
        env_keys=env_keys,
        docs=docs,
        privacy_note="The page is fetched by the provider, not from your machine.",
        capabilities=("static_html", "javascript", "hosted"),
        notes=notes,
    )

    return type(
        f"{label.replace(' ', '')}Provider",
        (ManagedFetchProvider,),
        {
            "descriptor": descriptor,
            "build": build,
            "normalize": normalize,
            "__doc__": f"{label} — {docs}",
        },
    )


# --------------------------------------------------------------------- vendors
ZenRowsProvider = _make(
    "zenrows",
    "ZenRows",
    ("ZENROWS_API_KEY",),
    "https://docs.zenrows.com/universal-scraper-api/api-reference",
    lambda self, request: ProviderCall(
        "GET",
        "https://api.zenrows.com/v1/",
        params={
            "apikey": self.key(),
            "url": request.url,
            **({"js_render": "true"} if request.render_js else {}),
            **({"proxy_country": request.country} if request.country else {}),
        },
    ),
)

ScrapingBeeProvider = _make(
    "scrapingbee",
    "ScrapingBee",
    ("SCRAPINGBEE_API_KEY",),
    "https://www.scrapingbee.com/documentation/",
    lambda self, request: ProviderCall(
        "GET",
        "https://app.scrapingbee.com/api/v1/",
        params={
            "api_key": self.key(),
            "url": request.url,
            "render_js": "true" if request.render_js else "false",
            **({"country_code": request.country} if request.country else {}),
        },
    ),
)

ScraperAPIProvider = _make(
    "scraperapi",
    "ScraperAPI",
    ("SCRAPERAPI_KEY",),
    "https://docs.scraperapi.com/",
    lambda self, request: ProviderCall(
        "GET",
        "https://api.scraperapi.com/",
        params={
            "api_key": self.key(),
            "url": request.url,
            **({"render": "true"} if request.render_js else {}),
            **({"country_code": request.country} if request.country else {}),
        },
    ),
)

ScrapingAntProvider = _make(
    "scrapingant",
    "ScrapingAnt",
    ("SCRAPINGANT_API_KEY",),
    "https://docs.scrapingant.com/",
    lambda self, request: ProviderCall(
        "GET",
        "https://api.scrapingant.com/v2/general",
        params={
            "url": request.url,
            "browser": "true" if request.render_js else "false",
            **({"proxy_country": request.country} if request.country else {}),
        },
        headers={"x-api-key": self.key()},
    ),
)

ScrapflyProvider = _make(
    "scrapfly",
    "Scrapfly",
    ("SCRAPFLY_API_KEY",),
    "https://scrapfly.io/docs/scrape-api/getting-started",
    lambda self, request: ProviderCall(
        "GET",
        "https://api.scrapfly.io/scrape",
        params={
            "key": self.key(),
            "url": request.url,
            **({"render_js": "true"} if request.render_js else {}),
            **({"country": request.country} if request.country else {}),
        },
    ),
    normalize=lambda self, payload: (
        (payload.get("result", {}) or {}).get("content", "")
        if isinstance(payload, dict)
        else _text(payload)
    ),
)

OxylabsProvider = _make(
    "oxylabs",
    "Oxylabs",
    ("OXYLABS_USERNAME", "OXYLABS_PASSWORD"),
    "https://developers.oxylabs.io/scraper-apis/web-scraper-api",
    lambda self, request: ProviderCall(
        "POST",
        "https://realtime.oxylabs.io/v1/queries",
        json_body={
            "source": "universal",
            "url": request.url,
            **({"render": "html"} if request.render_js else {}),
            **({"geo_location": request.country} if request.country else {}),
        },
        auth=(os.getenv("OXYLABS_USERNAME", ""), os.getenv("OXYLABS_PASSWORD", "")),
    ),
    normalize=lambda self, payload: (
        (payload.get("results") or [{}])[0].get("content", "")
        if isinstance(payload, dict)
        else _text(payload)
    ),
    notes="Uses the realtime endpoint with the universal source.",
)

BrightDataProvider = _make(
    "brightdata",
    "Bright Data",
    ("BRIGHTDATA_API_TOKEN",),
    "https://docs.brightdata.com/scraping-automation/web-unlocker/send-your-first-request",
    lambda self, request: ProviderCall(
        "POST",
        "https://api.brightdata.com/request",
        json_body={
            "zone": os.getenv("BRIGHTDATA_ZONE", "web_unlocker1"),
            "url": request.url,
            "format": "raw",
        },
        headers={"Authorization": f"Bearer {self.key()}", "Content-Type": "application/json"},
    ),
    notes="Set BRIGHTDATA_ZONE to the Web Unlocker zone name.",
)

ScrapelessProvider = _make(
    "scrapeless",
    "Scrapeless",
    ("SCRAPELESS_API_KEY",),
    "https://docs.scrapeless.com/",
    lambda self, request: ProviderCall(
        "POST",
        "https://api.scrapeless.com/api/v1/unlocker/request",
        json_body={
            "actor": "unlocker.webunlocker",
            "input": {
                "url": request.url,
                "js_render": request.render_js,
                **({"country": request.country} if request.country else {}),
            },
        },
        headers={"x-api-token": self.key(), "Content-Type": "application/json"},
    ),
    normalize=lambda self, payload: (
        payload.get("data", {}).get("content", "") or payload.get("html", "")
        if isinstance(payload, dict)
        else _text(payload)
    ),
)

NimbleProvider = _make(
    "nimble",
    "Nimble",
    ("NIMBLE_API_KEY",),
    "https://docs.nimbleway.com/",
    lambda self, request: ProviderCall(
        "POST",
        "https://api.webit.live/api/v1/realtime/web",
        json_body={
            "url": request.url,
            "method": "GET",
            "render": request.render_js,
            **({"country": request.country} if request.country else {}),
        },
        headers={"Authorization": f"Bearer {self.key()}", "Content-Type": "application/json"},
    ),
    normalize=lambda self, payload: (
        payload.get("html_content", "") or payload.get("content", "")
        if isinstance(payload, dict)
        else _text(payload)
    ),
)

ThordataProvider = _make(
    "thordata",
    "Thordata",
    ("THORDATA_API_KEY",),
    "https://www.thordata.com/documentation/",
    lambda self, request: ProviderCall(
        "POST",
        os.getenv("THORDATA_ENDPOINT", "https://universalapi.thordata.com/request"),
        json_body={
            "url": request.url,
            "type": "html",
            **({"js_render": "true"} if request.render_js else {}),
        },
        headers={"Authorization": f"Bearer {self.key()}", "Content-Type": "application/json"},
    ),
    normalize=lambda self, payload: (
        payload.get("data", "") or payload.get("html", "")
        if isinstance(payload, dict)
        else _text(payload)
    ),
    notes="Endpoint is configurable via THORDATA_ENDPOINT.",
)


PROVIDERS: dict[str, type[ManagedFetchProvider]] = {
    "zenrows": ZenRowsProvider,
    "scrapingbee": ScrapingBeeProvider,
    "scraperapi": ScraperAPIProvider,
    "scrapingant": ScrapingAntProvider,
    "scrapfly": ScrapflyProvider,
    "oxylabs": OxylabsProvider,
    "brightdata": BrightDataProvider,
    "scrapeless": ScrapelessProvider,
    "nimble": NimbleProvider,
    "thordata": ThordataProvider,
}


def providers() -> list[ManagedFetchProvider]:
    return [cls() for cls in PROVIDERS.values()]


def get_provider(name: str) -> ManagedFetchProvider | None:
    cls = PROVIDERS.get(name)
    return cls() if cls else None


def configured_provider(preferred: str | None = None) -> ManagedFetchProvider | None:
    if preferred:
        provider = get_provider(preferred)
        return provider if provider and provider.available() else None
    for provider in providers():
        if provider.available():
            return provider
    return None
