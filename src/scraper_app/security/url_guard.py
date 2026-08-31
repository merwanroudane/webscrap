"""SSRF-resistant URL guard (spec section 37).

Nothing in the application may issue an HTTP request without first passing the
target through :func:`guard_url`. Redirects are re-validated by the fetch layer
through the same function.

Reference: OWASP SSRF Prevention Cheat Sheet.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlparse, urlsplit, urlunsplit

from ..config import SETTINGS, SecurityPolicy
from ..exceptions import ErrorCode, UrlBlocked

_SCHEME_PREFIX = re.compile(r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.\-]*):")
_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")
_BLOCKED_HOST_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost"}


@dataclass(frozen=True)
class GuardedUrl:
    url: str
    scheme: str
    host: str
    port: int
    resolved_ips: tuple[str, ...]


def normalize_url(raw: str) -> str:
    """Add a scheme when the user pasted a bare domain and trim whitespace."""
    candidate = (raw or "").strip()
    if not candidate:
        raise UrlBlocked(ErrorCode.URL_INVALID, "Empty address.")
    scheme_match = _SCHEME_PREFIX.match(candidate)
    if scheme_match and "://" not in candidate:
        # A scheme without an authority (data:, file:, javascript:, mailto: ...).
        raise UrlBlocked(
            ErrorCode.URL_INVALID,
            f"Scheme {scheme_match.group('scheme').lower()!r} is not allowed; use http or https.",
        )
    if "://" not in candidate:
        candidate = "https://" + candidate.lstrip("/")
    parts = urlsplit(candidate)
    if not parts.netloc:
        raise UrlBlocked(ErrorCode.URL_INVALID, candidate)
    # Lowercase scheme/host, keep path and query untouched.
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
        return False
    if ip.is_reserved or ip.is_unspecified:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return _is_public_ip(ip.ipv4_mapped)
        if ip.is_site_local:
            return False
    return True


def _resolve(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:  # pragma: no cover - network dependent
        raise UrlBlocked(ErrorCode.CONNECTION_ERROR, f"Could not resolve host {host}.") from exc
    return sorted({info[4][0] for info in infos})


def guard_url(raw: str, policy: SecurityPolicy | None = None) -> GuardedUrl:
    """Validate a URL and every address it resolves to.

    Raises :class:`UrlBlocked` with a taxonomy code; never returns silently for
    a disallowed target.
    """
    policy = policy or SETTINGS.security
    url = normalize_url(raw)
    parts = urlparse(url)

    if parts.scheme not in policy.allowed_schemes:
        raise UrlBlocked(
            ErrorCode.URL_INVALID,
            f"Scheme {parts.scheme!r} is not allowed; use http or https.",
        )
    if (parts.username or parts.password) and not policy.allow_userinfo:
        raise UrlBlocked(
            ErrorCode.URL_INVALID,
            "Addresses embedding a username/password are not accepted.",
        )

    host = parts.hostname or ""
    if not host:
        raise UrlBlocked(ErrorCode.URL_INVALID, "Missing host name.")

    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise UrlBlocked(ErrorCode.URL_INVALID, "The address contains an invalid port.") from exc
    if port in policy.blocked_ports:
        raise UrlBlocked(ErrorCode.URL_INVALID, f"Port {port} is not allowed.")

    lowered = host.lower()
    # An explicitly allowed host:port (the bundled demo server) skips only the
    # non-public-address rule; every other check above and below still applies.
    explicitly_allowed = f"{lowered}:{port}" in policy.allow_hosts
    permit_private = policy.allow_private_networks or explicitly_allowed

    if lowered in _BLOCKED_HOST_NAMES or lowered.endswith(_BLOCKED_HOST_SUFFIXES):
        if not permit_private:
            raise UrlBlocked(ErrorCode.URL_PRIVATE_NETWORK_BLOCKED, host)
    if lowered in policy.metadata_hosts:
        raise UrlBlocked(ErrorCode.URL_PRIVATE_NETWORK_BLOCKED, "Cloud metadata endpoint.")

    # Literal IP or DNS resolution — both are validated.
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
        addresses = [str(literal)]
    except ValueError:
        addresses = _resolve(host)

    if not addresses:
        raise UrlBlocked(ErrorCode.CONNECTION_ERROR, f"No address found for {host}.")

    for addr in addresses:
        if addr in policy.metadata_hosts:
            raise UrlBlocked(ErrorCode.URL_PRIVATE_NETWORK_BLOCKED, "Cloud metadata endpoint.")
        ip = ipaddress.ip_address(addr)
        if not _is_public_ip(ip) and not permit_private:
            raise UrlBlocked(
                ErrorCode.URL_PRIVATE_NETWORK_BLOCKED,
                f"{host} resolves to the non-public address {addr}.",
            )

    return GuardedUrl(
        url=url,
        scheme=parts.scheme,
        host=host,
        port=port,
        resolved_ips=tuple(addresses),
    )


def is_allowed(raw: str) -> bool:
    """Boolean convenience wrapper used by link filtering during crawls."""
    try:
        guard_url(raw)
    except UrlBlocked:
        return False
    return True
