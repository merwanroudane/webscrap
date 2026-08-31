"""Bundled offline demo (spec section 106.9).

Starts the fixture server inside the Streamlit process so a new researcher can
follow the whole workflow without hunting for a live website.

The fixtures are served from 127.0.0.1, which the SSRF guard would normally
refuse. Rather than switching the private-network protection off, the demo
allow-lists the one exact ``host:port`` it just started — so a publicly hosted
instance of this app stays protected against every other internal address.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

TESTS_DIR = Path(__file__).resolve().parents[3] / "tests"


@st.cache_resource(show_spinner=False)
def _server():
    """Start (once per session) the local fixture server."""
    if str(TESTS_DIR) not in sys.path:
        sys.path.insert(0, str(TESTS_DIR))
    from fixture_server import FixtureServer  # type: ignore

    server = FixtureServer().start()
    return server


def ensure_demo_server() -> str:
    """Start the demo server and allow-list only its own address."""
    from ..config import allow_host

    server = _server()
    host, port = server.address
    allow_host(f"{host}:{port}")
    return server.base_url


def demo_url(path: str) -> str:
    return _server().url(path)


def demo_pages() -> list[tuple[str, str]]:
    return [
        ("Statistical table", "/table.html"),
        ("Repeated cards with pagination", "/cards.html"),
        ("JSON API", "/api/indicators?page=1"),
        ("JavaScript page with embedded JSON", "/js_page.html"),
        ("Article", "/article.html"),
        ("CSV file", "/data/indicators.csv"),
    ]


def is_demo_active() -> bool:
    """True once the demo server has been started in this process."""
    from ..config import SETTINGS

    return bool(SETTINGS.security.allow_hosts)
