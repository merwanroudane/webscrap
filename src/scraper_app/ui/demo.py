"""Bundled offline demo (spec section 106.9).

Starts the fixture server inside the Streamlit process so a new researcher can
follow the whole workflow without hunting for a live website. Because the
fixtures are served from 127.0.0.1, the demo enables the private-network
exception for the current process only, and only while the demo is running.
"""

from __future__ import annotations

import os
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
    """Start the demo server and allow loopback requests for this process."""
    os.environ["SRWS_ALLOW_PRIVATE_NETWORKS"] = "true"
    _reload_security_policy()
    return _server().base_url


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


def _reload_security_policy() -> None:
    """Re-read the env flag into the frozen settings object."""
    from .. import config

    policy = config.SecurityPolicy(allow_private_networks=True)
    object.__setattr__(config.SETTINGS, "security", policy)


def is_demo_active() -> bool:
    return os.getenv("SRWS_ALLOW_PRIVATE_NETWORKS", "").lower() in {"1", "true", "yes"}
