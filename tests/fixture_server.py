"""Deterministic local fixture server used by tests and the Try demo button.

Serves the bundled fixture site on 127.0.0.1 so no test depends on a live
website. Because the guard blocks private addresses by default, callers must
opt in via ``SRWS_ALLOW_PRIVATE_NETWORKS=true`` (the test suite does this).
"""

from __future__ import annotations

import json
import threading
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "site"

_API_ROWS = [
    {"country": "Algeria", "year": 2023, "value": 9.3, "unit": "percent"},
    {"country": "Morocco", "year": 2023, "value": 6.1, "unit": "percent"},
    {"country": "Tunisia", "year": 2023, "value": 9.3, "unit": "percent"},
    {"country": "Egypt", "year": 2023, "value": 33.9, "unit": "percent"},
    {"country": "Jordan", "year": 2023, "value": 2.1, "unit": "percent"},
    {"country": "Algeria", "year": 2022, "value": 9.3, "unit": "percent"},
]
PAGE_SIZE = 3


class FixtureHandler(SimpleHTTPRequestHandler):
    """Static fixtures plus a small paginated JSON API."""

    def log_message(self, *args) -> None:  # silence test output
        return

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        parts = urlsplit(self.path)
        if parts.path == "/api/indicators":
            page = int(parse_qs(parts.query).get("page", ["1"])[0])
            start = (page - 1) * PAGE_SIZE
            rows = _API_ROWS[start : start + PAGE_SIZE]
            payload = {
                "meta": {"page": page, "pages": 2, "per_page": PAGE_SIZE},
                "data": rows,
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parts.path == "/data/indicators.csv":
            body = (
                b"country,year,value\n"
                b"Algeria,2023,9.3\nMorocco,2023,6.1\nTunisia,2023,9.3\n"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/csv")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parts.path in {"/", ""}:
            self.path = "/table.html"
        super().do_GET()


class FixtureServer:
    """Context manager returning the base URL of a running fixture server."""

    def __init__(self, directory: Path | None = None) -> None:
        handler = partial(FixtureHandler, directory=str(directory or FIXTURE_DIR))
        self._server = HTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def start(self) -> FixtureServer:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self) -> FixtureServer:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
