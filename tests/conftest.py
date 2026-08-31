"""Shared pytest fixtures.

Every test runs against the bundled fixture server on 127.0.0.1, so the suite
never depends on a live website.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (str(SRC), str(ROOT / "tests")):
    if path not in sys.path:
        sys.path.insert(0, path)

# Loopback fixtures + fast rate limit, set before scraper_app.config is imported.
os.environ.setdefault("SRWS_ALLOW_PRIVATE_NETWORKS", "true")
os.environ.setdefault("SRWS_REQUESTS_PER_SECOND", "50")
os.environ.setdefault("SRWS_RUNS_DIR", str(ROOT / ".pytest_runs"))


@pytest.fixture(scope="session")
def server():
    from fixture_server import FixtureServer

    instance = FixtureServer().start()
    yield instance
    instance.stop()


@pytest.fixture(autouse=True)
def _clear_robots_cache():
    from scraper_app.security import robots

    robots.clear_cache()
    yield
