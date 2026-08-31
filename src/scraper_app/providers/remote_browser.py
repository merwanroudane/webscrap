"""Remote browser providers (audit section M).

One contract, four vendors. Each provider creates a hosted browser session and
returns a CDP endpoint; the existing Playwright workflow then connects to it
with ``connect_over_cdp`` instead of launching local Chromium. The browser
logic is not duplicated per vendor.

None of these is required. With no key configured the local Chromium path is
used exactly as before.
"""

from __future__ import annotations

import os
from abc import abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from ..config import SETTINGS
from ..exceptions import ErrorCode, ScraperError
from .base import BaseProvider, ProviderCategory, ProviderDescriptor

_TIMEOUT = 45.0


@dataclass
class RemoteSession:
    """A live hosted browser session."""

    provider: str
    session_id: str
    cdp_url: str
    raw: dict[str, Any]


class RemoteBrowserProvider(BaseProvider):
    """Create and release a hosted browser session."""

    @abstractmethod
    def create_session(self) -> RemoteSession: ...

    def close_session(self, session: RemoteSession) -> None:
        """Best-effort release. Providers that auto-expire may do nothing."""
        return None

    def describe(self) -> dict[str, Any]:
        return self.descriptor.as_row()

    @contextmanager
    def session(self):
        """Context manager yielding a :class:`RemoteSession`."""
        self._require_ready()
        created = self.create_session()
        try:
            yield created
        finally:
            try:
                self.close_session(created)
            except Exception:
                pass

    # ------------------------------------------------------------------ helpers
    def _post(
        self, url: str, *, headers: dict[str, str], json_body: dict[str, Any]
    ) -> dict[str, Any]:
        """POST to a provider control plane (not to a user-supplied target)."""
        import httpx

        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                response = client.post(url, headers=headers, json=json_body)
        except httpx.HTTPError as exc:
            raise ScraperError(
                ErrorCode.CONNECTION_ERROR,
                f"{self.label} could not be reached ({exc.__class__.__name__}).",
            ) from exc
        if response.status_code >= 400:
            raise ScraperError(
                ErrorCode.HTTP_ERROR,
                f"{self.label} returned {response.status_code} when creating a session.",
            )
        try:
            return response.json()
        except Exception as exc:
            raise ScraperError(
                ErrorCode.CONTENT_UNSUPPORTED, f"{self.label} returned a non-JSON session response."
            ) from exc


class BrowserbaseProvider(RemoteBrowserProvider):
    """https://docs.browserbase.com — POST /v1/sessions returns ``connectUrl``."""

    descriptor = ProviderDescriptor(
        id="browserbase",
        label="Browserbase",
        category=ProviderCategory.REMOTE_BROWSER,
        cost_mode="metered",
        env_keys=("BROWSERBASE_API_KEY",),
        docs="https://docs.browserbase.com/reference/api/create-a-session",
        privacy_note="Pages are loaded by Browserbase, not on your machine.",
        capabilities=("javascript", "network_capture", "hosted"),
    )

    def create_session(self) -> RemoteSession:
        body: dict[str, Any] = {}
        project = os.getenv("BROWSERBASE_PROJECT_ID", "").strip()
        if project:
            body["projectId"] = project
        payload = self._post(
            "https://api.browserbase.com/v1/sessions",
            headers={
                "X-BB-API-Key": os.environ["BROWSERBASE_API_KEY"],
                "Content-Type": "application/json",
            },
            json_body=body,
        )
        cdp = payload.get("connectUrl") or ""
        if not cdp:
            raise ScraperError(ErrorCode.INTERNAL, "Browserbase did not return a connect URL.")
        return RemoteSession("browserbase", str(payload.get("id", "")), cdp, payload)


class HyperbrowserProvider(RemoteBrowserProvider):
    """https://docs.hyperbrowser.ai — POST /api/session returns ``wsEndpoint``."""

    descriptor = ProviderDescriptor(
        id="hyperbrowser",
        label="Hyperbrowser",
        category=ProviderCategory.REMOTE_BROWSER,
        cost_mode="metered",
        env_keys=("HYPERBROWSER_API_KEY",),
        docs="https://docs.hyperbrowser.ai/",
        privacy_note="Pages are loaded by Hyperbrowser, not on your machine.",
        capabilities=("javascript", "hosted"),
    )

    def create_session(self) -> RemoteSession:
        payload = self._post(
            "https://api.hyperbrowser.ai/api/session",
            headers={
                "x-api-key": os.environ["HYPERBROWSER_API_KEY"],
                "Content-Type": "application/json",
            },
            json_body={},
        )
        cdp = payload.get("wsEndpoint") or payload.get("connectUrl") or ""
        if not cdp:
            raise ScraperError(
                ErrorCode.INTERNAL, "Hyperbrowser did not return a websocket endpoint."
            )
        return RemoteSession("hyperbrowser", str(payload.get("id", "")), cdp, payload)


class SteelProvider(RemoteBrowserProvider):
    """https://docs.steel.dev — POST /v1/sessions, connect to ``/v1/devtools/browser/<id>``."""

    descriptor = ProviderDescriptor(
        id="steel",
        label="Steel",
        category=ProviderCategory.REMOTE_BROWSER,
        cost_mode="metered",
        env_keys=("STEEL_API_KEY",),
        docs="https://docs.steel.dev/",
        privacy_note="Pages are loaded by Steel, not on your machine.",
        capabilities=("javascript", "hosted"),
    )

    def create_session(self) -> RemoteSession:
        base = os.getenv("STEEL_BASE_URL", "https://api.steel.dev").rstrip("/")
        payload = self._post(
            f"{base}/v1/sessions",
            headers={
                "steel-api-key": os.environ["STEEL_API_KEY"],
                "Content-Type": "application/json",
            },
            json_body={},
        )
        session_id = str(payload.get("id", ""))
        cdp = payload.get("websocketUrl") or payload.get("connectUrl") or ""
        if not cdp and session_id:
            key = os.environ["STEEL_API_KEY"]
            cdp = f"{base.replace('https://', 'wss://')}/v1/devtools/browser/{session_id}?apiKey={key}"
        if not cdp:
            raise ScraperError(ErrorCode.INTERNAL, "Steel did not return a connectable session.")
        return RemoteSession("steel", session_id, cdp, payload)

    def close_session(self, session: RemoteSession) -> None:  # pragma: no cover - network
        import httpx

        base = os.getenv("STEEL_BASE_URL", "https://api.steel.dev").rstrip("/")
        if not session.session_id:
            return
        with httpx.Client(timeout=15.0) as client:
            client.post(
                f"{base}/v1/sessions/{session.session_id}/release",
                headers={"steel-api-key": os.environ["STEEL_API_KEY"]},
            )


class BrowserlessProvider(RemoteBrowserProvider):
    """https://docs.browserless.io — connect straight to a token-scoped websocket."""

    descriptor = ProviderDescriptor(
        id="browserless",
        label="Browserless",
        category=ProviderCategory.REMOTE_BROWSER,
        cost_mode="metered",
        env_keys=("BROWSERLESS_TOKEN",),
        docs="https://docs.browserless.io/",
        privacy_note="Pages are loaded by Browserless, not on your machine.",
        capabilities=("javascript", "hosted"),
        notes="Self-hosted instances work too — set BROWSERLESS_URL.",
    )

    def create_session(self) -> RemoteSession:
        # Browserless has no session control plane: the websocket *is* the session.
        base = os.getenv("BROWSERLESS_URL", "wss://production-sfo.browserless.io").rstrip("/")
        token = os.environ["BROWSERLESS_TOKEN"]
        if base.startswith("http://"):
            base = "ws://" + base[len("http://") :]
        elif base.startswith("https://"):
            base = "wss://" + base[len("https://") :]
        return RemoteSession("browserless", "", f"{base}?token={token}", {})


PROVIDERS: dict[str, type[RemoteBrowserProvider]] = {
    "browserbase": BrowserbaseProvider,
    "hyperbrowser": HyperbrowserProvider,
    "steel": SteelProvider,
    "browserless": BrowserlessProvider,
}


def providers() -> list[RemoteBrowserProvider]:
    return [cls() for cls in PROVIDERS.values()]


def get_provider(name: str) -> RemoteBrowserProvider | None:
    cls = PROVIDERS.get(name)
    return cls() if cls else None


def configured_provider(preferred: str | None = None) -> RemoteBrowserProvider | None:
    """Return a usable remote browser, or ``None`` to use local Chromium."""
    if preferred:
        provider = get_provider(preferred)
        return provider if provider and provider.available() else None
    for provider in providers():
        if provider.available():
            return provider
    return None


@contextmanager
def browser_context(provider: RemoteBrowserProvider | None = None, headless: bool = True):
    """Yield ``(playwright_browser, description)`` for local or remote Chromium.

    The rest of the application uses this instead of launching a browser
    directly, so remote providers require no changes in the engines.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        if provider is None:
            browser = p.chromium.launch(headless=headless)
            try:
                yield browser, "local Chromium"
            finally:
                browser.close()
            return

        with provider.session() as remote:  # pragma: no cover - requires credentials
            browser = p.chromium.connect_over_cdp(remote.cdp_url, timeout=int(_TIMEOUT * 1000))
            try:
                yield browser, f"{provider.label} (remote)"
            finally:
                browser.close()


def user_agent() -> str:
    return SETTINGS.user_agent
