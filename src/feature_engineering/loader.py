"""Preparation-manifest-first batch resolution and Parquet loading."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.feature_engineering.errors import PreparedBatchNotFoundError

REQUIRED = (
    "users_prepared", "products_prepared", "interactions_prepared",
    "user_product_interactions", "train", "validation", "test",
)


@dataclass(frozen=True)
class PreparedBatch:
    """Resolved prepared batch and immutable source lineage."""

    batch_id: str
    preparation_run_id: str
    correlation_id: str
    manifest_path: Path
    paths: dict[str, Path]
    checksums: dict[str, str]


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 file checksum."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_prepared_batch(
    root: Path, batch_id: str | None = None
) -> PreparedBatch:
    """Resolve latest/requested successful prepared batch via its manifest."""
    candidates: list[tuple[datetime, Path, dict[str, Any]]] = []
    for path in root.rglob("preparation_manifest.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload["status"] not in {"SUCCESS", "COMPLETED_WITH_WARNINGS"}:
                continue
            if batch_id and payload["batch_id"] != batch_id:
                continue
            started = datetime.fromisoformat(
                payload["started_at"].replace("Z", "+00:00")
            )
            candidates.append((started, path, payload))
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            continue
    if not candidates:
        raise PreparedBatchNotFoundError(
            f"No eligible prepared batch found under {root}."
        )
    _, manifest_path, manifest = max(candidates, key=lambda item: item[0])
    declared = manifest["output_dataset_paths"]
    missing = set(REQUIRED).difference(declared)
    if missing:
        raise PreparedBatchNotFoundError(
            "Preparation manifest lacks inputs: " + ", ".join(sorted(missing))
        )
    paths: dict[str, Path] = {}
    checksums: dict[str, str] = {}
    for name in REQUIRED:
        path = Path(declared[name]).resolve()
        if not path.is_file():
            raise PreparedBatchNotFoundError(
                f"Prepared input is missing: {path}"
            )
        paths[name] = path
        checksums[name] = sha256_file(path)
    return PreparedBatch(
        batch_id=manifest["batch_id"],
        preparation_run_id=manifest["preparation_run_id"],
        correlation_id=manifest["correlation_id"],
        manifest_path=manifest_path.resolve(),
        paths=paths,
        checksums=checksums,
    )


def load_prepared(batch: PreparedBatch) -> dict[str, pd.DataFrame]:
    """Load only preparation-manifest-declared Parquet inputs."""
    try:
        return {
            name: pd.read_parquet(path)
            for name, path in batch.paths.items()
        }
    except (OSError, ValueError) as exc:
        raise PreparedBatchNotFoundError(
            "Unable to load prepared Parquet inputs."
        ) from exc
