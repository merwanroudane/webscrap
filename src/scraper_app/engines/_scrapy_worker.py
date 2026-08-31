"""Out-of-process Scrapy runner (audit v0.2 section 32).

Scrapy runs on Twisted, and a Twisted reactor cannot be restarted once it has
been stopped. Calling ``CrawlerProcess.start()`` inside the Streamlit process
therefore works exactly once: the second extraction in the same session raises
``ReactorNotRestartable``.

This module is that call, moved into a throwaway subprocess. Every crawl gets a
fresh interpreter and therefore a fresh reactor, so the second run behaves like
the first. It also keeps Twisted's signal handlers and logging out of the
Streamlit runtime entirely.

It is deliberately standalone — it imports only the standard library and Scrapy,
never ``scraper_app`` — so the subprocess needs no knowledge of where the
application is installed.

Contract::

    python _scrapy_worker.py <config.json>

``config.json``::

    {"urls": [...], "output": "<path>", "settings": {...}, "max_bytes": 5000000}

The output file receives ``{"pages": [[url, html], ...], "error": null}``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(config_path: str) -> int:
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    urls: list[str] = list(config["urls"])
    output = Path(config["output"])
    settings: dict = dict(config.get("settings") or {})
    max_bytes = int(config.get("max_bytes") or 5_000_000)

    collected: list[list[str]] = []
    error: str | None = None

    try:
        import scrapy
        from scrapy.crawler import CrawlerProcess

        class CollectSpider(scrapy.Spider):
            name = "srws_collect"
            start_urls = list(urls)
            custom_settings = settings

            def parse(self, response):  # noqa: ANN001, D401
                text = response.text or ""
                collected.append([response.url, text[:max_bytes]])

        process = CrawlerProcess(settings={"LOG_ENABLED": False})
        process.crawl(CollectSpider)
        process.start()  # blocks until the crawl finishes
    except Exception as exc:  # noqa: BLE001 - reported to the parent, not raised
        error = f"{exc.__class__.__name__}: {exc}"

    output.write_text(
        json.dumps({"pages": collected, "error": error}, ensure_ascii=False),
        encoding="utf-8",
    )
    return 0 if error is None else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: _scrapy_worker.py <config.json>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
