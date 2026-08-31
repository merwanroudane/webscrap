"""Structured, sanitized run logging (spec section 65).

Events are kept in memory per run so the Diagnostics tab can show a readable
technical log. Secrets never enter a record: URLs pass through
``sanitize_url`` and free text through ``sanitize_text``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .security.secrets import sanitize_text, sanitize_url

_LOGGER = logging.getLogger("scraper_app")
if not _LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    _LOGGER.addHandler(handler)
    _LOGGER.setLevel(logging.INFO)


@dataclass
class LogEvent:
    timestamp: float
    run_id: str
    level: str
    component: str
    event: str
    status: str = ""
    engine: str = ""
    url: str = ""
    elapsed_ms: int | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def as_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["time"] = time.strftime("%H:%M:%S", time.localtime(self.timestamp))
        return row


class RunLogger:
    """Collects sanitized events for a single extraction run."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.events: list[LogEvent] = []
        self._started = time.time()

    def log(
        self,
        component: str,
        event: str,
        *,
        level: str = "info",
        status: str = "",
        engine: str = "",
        url: str = "",
        elapsed_ms: int | None = None,
        **detail: Any,
    ) -> LogEvent:
        record = LogEvent(
            timestamp=time.time(),
            run_id=self.run_id,
            level=level,
            component=component,
            event=sanitize_text(event),
            status=status,
            engine=engine,
            url=sanitize_url(url) if url else "",
            elapsed_ms=elapsed_ms,
            detail={k: _sanitize_value(v) for k, v in detail.items()},
        )
        self.events.append(record)
        _LOGGER.log(
            getattr(logging, level.upper(), logging.INFO),
            "[%s] %s.%s %s",
            self.run_id,
            component,
            event,
            record.url,
        )
        return record

    def warn(self, component: str, event: str, **detail: Any) -> LogEvent:
        return self.log(component, event, level="warning", **detail)

    def error(self, component: str, event: str, **detail: Any) -> LogEvent:
        return self.log(component, event, level="error", **detail)

    def rows(self) -> list[dict[str, Any]]:
        return [event.as_row() for event in self.events]

    @property
    def elapsed_ms(self) -> int:
        return int((time.time() - self._started) * 1000)


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, dict):
        return {k: _sanitize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(v) for v in value]
    return value


def get_logger(run_id: str) -> RunLogger:
    return RunLogger(run_id)
