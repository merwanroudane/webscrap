"""Guarded, polite HTTP layer used by every deterministic engine.

Responsibilities:

* run every URL (including each redirect hop) through the SSRF guard;
* enforce per-host rate limiting and jitter (spec section 39);
* retry with exponential backoff, honouring ``Retry-After`` on 429;
* bound response size (spec section 70);
* translate transport failures into the error taxonomy.
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from ..config import SETTINGS
from ..exceptions import ErrorCode, ScraperError, http_status_code
from ..security.url_guard import guard_url

_rate_lock = threading.Lock()
_last_request_at: dict[str, float] = {}


@dataclass
class FetchResponse:
    url: str
    status_code: int
    headers: dict[str, str]
    content: bytes
    encoding: str | None = None
    elapsed_ms: int = 0
    truncated: bool = False
    history: list[str] = field(default_factory=list)

    @property
    def content_type(self) -> str:
        return (self.headers.get("content-type") or "").split(";")[0].strip().lower()

    @property
    def text(self) -> str:
        enc = self.encoding or "utf-8"
        try:
            return self.content.decode(enc, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        import json

        return json.loads(self.text)


def _throttle(host: str, requests_per_second: float | None = None) -> None:
    rps = requests_per_second or SETTINGS.politeness.requests_per_second
    if rps <= 0:
        return
    min_interval = 1.0 / rps
    with _rate_lock:
        now = time.monotonic()
        last = _last_request_at.get(host)
        if last is not None:
            wait = min_interval - (now - last)
            if wait > 0:
                time.sleep(wait + random.uniform(0, SETTINGS.politeness.jitter_seconds))
        _last_request_at[host] = time.monotonic()


def _read_bounded(response: httpx.Response, max_bytes: int) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    total = 0
    truncated = False
    for chunk in response.iter_bytes():
        chunks.append(chunk)
        total += len(chunk)
        if total >= max_bytes:
            truncated = True
            break
    return b"".join(chunks)[:max_bytes], truncated


def fetch(
    url: str,
    *,
    method: str = "GET",
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    data: str | bytes | None = None,
    json_body: Any | None = None,
    timeout: float | None = None,
    max_bytes: int | None = None,
    requests_per_second: float | None = None,
    max_retries: int | None = None,
    allow_status: tuple[int, ...] = (),
) -> FetchResponse:
    """Perform one guarded HTTP request and return a bounded response."""
    guarded = guard_url(url)
    max_bytes = max_bytes or SETTINGS.limits.max_html_bytes
    timeout = timeout or SETTINGS.limits.http_timeout
    retries = SETTINGS.politeness.max_retries if max_retries is None else max_retries
    request_headers = {**SETTINGS.default_headers, **(headers or {})}

    attempt = 0
    last_error: Exception | None = None
    result: FetchResponse | None = None
    started = time.monotonic()

    while attempt <= retries:
        attempt += 1
        _throttle(guarded.host, requests_per_second)
        try:
            with httpx.Client(
                follow_redirects=False,
                timeout=timeout,
                headers=request_headers,
                cookies=cookies or {},
            ) as client:
                current = guarded.url
                history: list[str] = []
                for _hop in range(SETTINGS.limits.max_redirects + 1):
                    with client.stream(
                        method,
                        current,
                        params=params,
                        content=data,
                        json=json_body,
                    ) as response:
                        if response.is_redirect:
                            location = response.headers.get("location", "")
                            if not location:
                                break
                            nxt = urljoin(current, location)
                            guard_url(nxt)  # re-validate every hop
                            history.append(current)
                            current = nxt
                            params = None  # already encoded in the redirect target
                            continue
                        payload, truncated = _read_bounded(response, max_bytes)
                        result = FetchResponse(
                            url=str(response.url),
                            status_code=response.status_code,
                            headers={k.lower(): v for k, v in response.headers.items()},
                            content=payload,
                            encoding=response.encoding,
                            elapsed_ms=int((time.monotonic() - started) * 1000),
                            truncated=truncated,
                            history=history,
                        )
                        break
                else:
                    raise ScraperError(
                        ErrorCode.HTTP_ERROR, "Too many redirects.", {"url": guarded.url}
                    )
        except ScraperError:
            raise
        except httpx.TimeoutException as exc:
            last_error = exc
            if attempt > retries:
                raise ScraperError(ErrorCode.TIMEOUT, guarded.host) from exc
            time.sleep(SETTINGS.politeness.backoff_factor**attempt)
            continue
        except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as exc:
            last_error = exc
            if attempt > retries:
                raise ScraperError(ErrorCode.CONNECTION_ERROR, guarded.host) from exc
            time.sleep(SETTINGS.politeness.backoff_factor**attempt)
            continue
        except httpx.HTTPError as exc:
            message = str(exc).lower()
            code = (
                ErrorCode.SSL_ERROR
                if "ssl" in message or "certificate" in message
                else ErrorCode.CONNECTION_ERROR
            )
            raise ScraperError(code, guarded.host) from exc

        if result is None:
            # Redirect without a Location header: nothing more to try.
            break
        if result.status_code == 429 and attempt <= retries:
            delay = _retry_after(result) or SETTINGS.politeness.backoff_factor**attempt
            time.sleep(min(delay, 30.0))
            continue
        if result.status_code >= 500 and attempt <= retries:
            time.sleep(SETTINGS.politeness.backoff_factor**attempt)
            continue
        break

    if result is None:  # pragma: no cover - defensive
        raise ScraperError(
            ErrorCode.CONNECTION_ERROR,
            f"{guarded.host} ({last_error.__class__.__name__ if last_error else 'no response'})",
        )

    if result.status_code >= 400 and result.status_code not in allow_status:
        raise ScraperError(
            http_status_code(result.status_code),
            f"{result.status_code} for {guarded.host}",
            {"url": result.url, "status": result.status_code},
        )
    return result


def _retry_after(response: FetchResponse) -> float | None:
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def fetch_text_simple(url: str, timeout: float = 10.0) -> tuple[int, str]:
    """Small helper for robots.txt / sitemaps: never raises on 4xx."""
    try:
        response = fetch(
            url,
            timeout=timeout,
            max_bytes=1024 * 1024,
            max_retries=0,
            allow_status=tuple(range(400, 600)),
        )
    except ScraperError:
        raise
    return response.status_code, response.text


def head_or_get(url: str, timeout: float | None = None) -> FetchResponse:
    """Try HEAD first (cheap), fall back to a bounded GET when unsupported."""
    try:
        response = fetch(
            url,
            method="HEAD",
            timeout=timeout,
            max_retries=0,
            allow_status=tuple(range(400, 600)),
        )
        if response.status_code < 400 and response.content_type:
            return response
    except ScraperError:
        pass
    return fetch(url, timeout=timeout)


def host_of(url: str) -> str:
    return urlsplit(url).netloc.lower()
