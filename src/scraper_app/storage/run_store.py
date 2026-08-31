"""Run artifacts and history (spec sections 43, 44, page 10).

Large datasets are kept as Parquet artifacts on disk rather than as Python
lists in Streamlit session state, and each run writes a small JSON manifest so
the History page can list and re-run past extractions.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import RUNS_DIR, ensure_dirs

PARQUET_THRESHOLD_ROWS = 50_000


def new_run_id() -> str:
    return f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


@dataclass
class RunRecord:
    run_id: str
    created_at: str
    source_url: str
    engine: str
    rows: int
    columns: int
    title: str = ""
    recipe_hash: str = ""
    has_data: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "source_url": self.source_url,
            "engine": self.engine,
            "rows": self.rows,
            "columns": self.columns,
            "title": self.title,
            "recipe_hash": self.recipe_hash,
            "has_data": self.has_data,
            **self.extra,
        }


def run_dir(run_id: str) -> Path:
    ensure_dirs()
    path = RUNS_DIR / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_frame(run_id: str, frame: pd.DataFrame, name: str = "dataset") -> Path:
    """Persist a dataset as Parquet (falls back to CSV when Arrow refuses)."""
    directory = run_dir(run_id)
    path = directory / f"{name}.parquet"
    try:
        frame.to_parquet(path, index=False)
    except Exception:
        path = directory / f"{name}.csv"
        frame.to_csv(path, index=False)
    return path


def load_frame(run_id: str, name: str = "dataset") -> pd.DataFrame | None:
    directory = RUNS_DIR / run_id
    parquet = directory / f"{name}.parquet"
    csv = directory / f"{name}.csv"
    if parquet.exists():
        return pd.read_parquet(parquet)
    if csv.exists():
        return pd.read_csv(csv)
    return None


def save_artifact(run_id: str, name: str, payload: bytes | str) -> Path:
    path = run_dir(run_id) / name
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_bytes(payload)
    return path


def save_manifest(record: RunRecord) -> Path:
    path = run_dir(record.run_id) / "manifest.json"
    path.write_text(json.dumps(record.as_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def list_runs(limit: int = 50) -> list[RunRecord]:
    """Most recent runs first."""
    ensure_dirs()
    records: list[RunRecord] = []
    for directory in sorted(RUNS_DIR.glob("*"), reverse=True):
        manifest = directory / "manifest.json"
        if not manifest.exists():
            continue
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            records.append(
                RunRecord(
                    run_id=payload.get("run_id", directory.name),
                    created_at=payload.get("created_at", ""),
                    source_url=payload.get("source_url", ""),
                    engine=payload.get("engine", ""),
                    rows=int(payload.get("rows", 0)),
                    columns=int(payload.get("columns", 0)),
                    title=payload.get("title", ""),
                    recipe_hash=payload.get("recipe_hash", ""),
                    has_data=bool(payload.get("has_data", False)),
                )
            )
        except Exception:
            continue
        if len(records) >= limit:
            break
    return records


def load_recipe(run_id: str) -> dict[str, Any] | None:
    path = RUNS_DIR / run_id / "extraction_recipe.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def delete_run(run_id: str) -> bool:
    import shutil

    directory = RUNS_DIR / run_id
    if directory.exists():
        shutil.rmtree(directory, ignore_errors=True)
        return True
    return False


def clear_all_runs() -> int:
    removed = 0
    for directory in list(RUNS_DIR.glob("*")):
        if directory.is_dir():
            delete_run(directory.name)
            removed += 1
    return removed
