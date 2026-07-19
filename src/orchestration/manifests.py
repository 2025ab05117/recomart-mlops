"""Manifest discovery helpers used by Airflow task wrappers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.orchestration.errors import StageExecutionError


def read_json(path: str | Path) -> dict[str, Any]:
    """Read one JSON object and fail with stage-oriented diagnostics."""
    resolved = Path(path)
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StageExecutionError(
            f"Unable to read stage manifest: {resolved}"
        ) from exc
    if not isinstance(payload, dict):
        raise StageExecutionError(f"Manifest is not a JSON object: {resolved}")
    return payload


def find_manifest(
    root: str | Path,
    filename: str,
    *,
    batch_id: str | None = None,
) -> Path:
    """Resolve the newest matching manifest without scanning data payloads."""
    base = Path(root)
    candidates = list(base.rglob(filename)) if base.exists() else []
    if batch_id:
        marker = f"batch_id={batch_id}"
        candidates = [path for path in candidates if marker in path.parts]
    if not candidates:
        suffix = f" for batch {batch_id}" if batch_id else ""
        raise StageExecutionError(
            f"No {filename} found under {base}{suffix}."
        )
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


def total_records(dataset_entries: list[dict[str, Any]]) -> int:
    """Return the sum of available dataset record counters."""
    return sum(
        int(item.get("record_count", item.get("total_records", 0)) or 0)
        for item in dataset_entries
    )
