"""Manifest-first validated batch resolution and loading."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.preparation.errors import (
    DatasetPreparationError,
    ValidatedBatchNotFoundError,
)

DATASETS = ("users", "products", "clickstream", "purchasehistory", "popularity")


@dataclass(frozen=True)
class ValidatedBatch:
    """Validation-manifest-backed batch and loaded dataset paths."""

    batch_id: str
    correlation_id: str
    validation_run_id: str
    manifest_path: Path
    paths: dict[str, Path]
    checksums: dict[str, str]


def file_sha256(path: Path) -> str:
    """Calculate a file SHA-256 checksum."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_validated_batch(
    report_root: Path,
    batch_id: str | None = None,
) -> ValidatedBatch:
    """Resolve the latest eligible manifest without scanning data folders."""
    candidates: list[tuple[datetime, Path, dict[str, Any]]] = []
    for path in report_root.rglob("validation_manifest.json"):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if manifest["status"] not in {
                "SUCCESS", "COMPLETED_WITH_QUALITY_ISSUES"
            }:
                continue
            if batch_id and manifest["batch_id"] != batch_id:
                continue
            started = datetime.fromisoformat(
                manifest["started_at"].replace("Z", "+00:00")
            )
            candidates.append((started, path, manifest))
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            continue
    if not candidates:
        raise ValidatedBatchNotFoundError(
            f"No eligible validated batch found under {report_root}."
        )
    _, manifest_path, manifest = max(candidates, key=lambda item: item[0])
    records = {item["dataset_type"]: item for item in manifest["datasets"]}
    missing = set(DATASETS).difference(records)
    if missing:
        raise ValidatedBatchNotFoundError(
            "Validation manifest is missing datasets: " + ", ".join(missing)
        )
    paths: dict[str, Path] = {}
    checksums: dict[str, str] = {}
    for dataset in DATASETS:
        path = Path(records[dataset]["validated_path"]).resolve()
        if not path.is_file():
            raise ValidatedBatchNotFoundError(
                f"Validated {dataset} file is missing: {path}"
            )
        paths[dataset] = path
        checksums[dataset] = file_sha256(path)
    return ValidatedBatch(
        batch_id=manifest["batch_id"],
        correlation_id=manifest["correlation_id"],
        validation_run_id=manifest["validation_run_id"],
        manifest_path=manifest_path.resolve(),
        paths=paths,
        checksums=checksums,
    )


def load_validated_datasets(batch: ValidatedBatch) -> dict[str, pd.DataFrame]:
    """Load only paths declared as validated by the validation manifest."""
    frames: dict[str, pd.DataFrame] = {}
    try:
        for dataset, path in batch.paths.items():
            if path.suffix.lower() == ".csv":
                frames[dataset] = pd.read_csv(path)
            else:
                payload = json.loads(path.read_text(encoding="utf-8") or "[]")
                if not isinstance(payload, list):
                    raise DatasetPreparationError(
                        f"{dataset} must be a JSON array."
                    )
                frames[dataset] = pd.DataFrame(payload)
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        raise DatasetPreparationError("Unable to load validated datasets.") from exc
    return frames
