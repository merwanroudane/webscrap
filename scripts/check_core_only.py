"""Verify the application is usable with only the core dependencies installed.

Run in CI on an environment built from ``requirements.txt`` alone. It asserts
the rule that no missing optional package may break import, startup or the
capability registry.

    python scripts/check_core_only.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

VALID_STATES = {"ready", "optional", "not_configured", "catalogue", "blocked"}


def main() -> int:
    # 1. Everything the Streamlit entry point touches must import cleanly.
    import scraper_app.service  # noqa: F401
    import scraper_app.ui.dataset_builder  # noqa: F401
    import scraper_app.ui.extraction_run  # noqa: F401
    import scraper_app.ui.help_page  # noqa: F401
    import scraper_app.ui.history  # noqa: F401
    import scraper_app.ui.home  # noqa: F401
    import scraper_app.ui.settings  # noqa: F401
    import scraper_app.ui.source_analysis  # noqa: F401
    import scraper_app.ui.workspace  # noqa: F401
    from scraper_app.routing.capability_registry import engine_instances, engine_status_table

    # 2. Every engine must answer availability() without raising.
    for name, engine in engine_instances().items():
        availability = engine.availability()
        assert isinstance(availability.ready, bool), name
        if not availability.ready:
            assert availability.reason, f"{name} is unavailable without saying why"

    # 3. The registry must report honest, known states.
    rows = engine_status_table()
    unknown = [r for r in rows if r.state not in VALID_STATES]
    assert not unknown, f"unknown provider states: {[(r.name, r.state) for r in unknown]}"

    ready = [r.label for r in rows if r.state == "ready"]
    assert ready, "a core-only installation reported no ready engine"

    # 4. A core-only install must still be able to export the common formats.
    import pandas as pd

    from scraper_app.export import exporters

    frame = pd.DataFrame({"country": ["A", "B"], "value": [1.0, 2.0]})
    available = {fmt.key for fmt, support in exporters.available_formats(frame) if support.ok}
    for required in ("csv", "json", "xlsx", "parquet"):
        assert required in available, f"{required} export unavailable in a core install"

    print(f"core-only check passed: {len(rows)} providers listed, {len(ready)} ready")
    print("  ready:", ", ".join(sorted(ready)))
    print("  exports:", ", ".join(sorted(available)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
