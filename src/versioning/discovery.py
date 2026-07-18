"""Manifest-driven discovery of existing pipeline artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.versioning.checksums import sha256_artifact
from src.versioning.config import VersioningConfig
from src.versioning.errors import RegistryError


@dataclass(frozen=True)
class ArtifactObservation:
    """Observed artifact and metadata reused from its producing manifest."""

    dataset_name: str
    pipeline_stage: str
    batch_id: str
    run_id: str
    created_at: str
    checksum: str
    record_count: int
    schema_version: str
    storage_location: str
    manifest_path: str
    configuration_hash: str
    transformation: str
    parent_name: str | None
    details: dict[str, Any]


def _latest(
    root: Path, filename: str, *, batch_id: str | None = None
) -> tuple[Path, dict[str, Any]]:
    candidates: list[tuple[Path, dict[str, Any]]] = []
    for path in root.rglob(filename):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        manifest_batch = (
            data.get("batch_id")
            or data.get("source_batch_id")
            or data.get("training_batch_id")
        )
        if batch_id and manifest_batch != batch_id:
            continue
        if data.get("status") == "FAILED":
            continue
        candidates.append((path, data))
    if not candidates:
        raise RegistryError(
            f"No usable {filename} found under {root}"
            + (f" for batch {batch_id}" if batch_id else "")
        )
    return max(
        candidates,
        key=lambda item: (
            item[1].get("completed_at", ""),
            item[0].stat().st_mtime_ns,
        ),
    )


def _relative(config: VersioningConfig, path: Path) -> str:
    try:
        return path.resolve().relative_to(config.root).as_posix()
    except ValueError:
        return str(path.resolve())


def discover_artifact(
    config: VersioningConfig,
    stage: str,
    *,
    batch_id: str | None = None,
) -> ArtifactObservation:
    """Resolve one stage from existing manifests without scanning its parents."""
    if stage not in config.artifacts:
        raise RegistryError(f"Unknown versioning stage: {stage}")
    definition = config.artifacts[stage]
    location = (config.root / definition["location"]).resolve()
    manifest_path: Path
    data: dict[str, Any]

    if stage in {"incoming", "raw"}:
        manifest_path, data = _latest(
            config.root / "data/raw", "ingestion_manifest.json",
            batch_id=batch_id,
        )
        count = sum(
            int(item.get("record_count", 0)) for item in data.get("files", [])
            if item.get("status") == "SUCCESS"
        )
        run_id = str(data.get("run_id", ""))
        created_at = str(data.get("completed_at", data.get("started_at", "")))
        schema_version = str(data.get("manifest_version", "1.0"))
        configuration_hash = ""
    elif stage == "validated":
        manifest_path, data = _latest(
            config.root / "reports/data_quality", "validation_manifest.json",
            batch_id=batch_id,
        )
        count = sum(
            int(item.get("valid_records", 0))
            for item in data.get("datasets", [])
        )
        run_id = str(data.get("validation_run_id", ""))
        created_at = str(data.get("completed_at", data.get("started_at", "")))
        schema_version = str(data.get("configuration_version", "1.0"))
        configuration_hash = str(data.get("configuration_sha256", ""))
    elif stage in {"prepared", "eda_reports"}:
        manifest_path, data = _latest(
            config.root / "data/prepared", "preparation_manifest.json",
            batch_id=batch_id,
        )
        count = sum(int(value) for value in data.get("records_produced", {}).values())
        run_id = str(data.get("preparation_run_id", ""))
        created_at = str(data.get("completed_at", data.get("started_at", "")))
        schema_version = str(data.get("transformation_version", "1.0"))
        configuration_hash = str(data.get("configuration_sha256", ""))
    elif stage == "features":
        manifest_path, data = _latest(
            config.root / "data/features", "feature_manifest.json",
            batch_id=batch_id,
        )
        count = sum(int(value) for value in data.get("row_counts", {}).values())
        run_id = str(data.get("feature_batch_id", ""))
        created_at = str(data.get("completed_at", data.get("started_at", "")))
        schema_version = str(data.get("feature_version", "1.0"))
        configuration_hash = str(data.get("configuration_hash", ""))
    else:
        manifest_path, data = _latest(
            config.root / "reports/model_training", "training_summary.json",
            batch_id=batch_id,
        )
        count = len(data.get("models", {})) if stage == "models" else len(
            list(location.rglob("*"))
        )
        run_id = str(data.get("model_run_id", ""))
        created_at = str(data.get("completed_at", data.get("started_at", "")))
        schema_version = str(
            config.versions[stage].split(".", maxsplit=1)[0]
        )
        configuration_hash = str(data.get("configuration_hash", ""))

    resolved_batch = str(
        data.get("batch_id")
        or data.get("source_batch_id")
        or data.get("training_batch_id")
        or ""
    )
    return ArtifactObservation(
        dataset_name=stage,
        pipeline_stage=stage,
        batch_id=resolved_batch,
        run_id=run_id,
        created_at=created_at,
        checksum=sha256_artifact(location),
        record_count=count,
        schema_version=schema_version,
        storage_location=_relative(config, location),
        manifest_path=_relative(config, manifest_path),
        configuration_hash=configuration_hash,
        transformation=str(definition["transformation"]),
        parent_name=definition.get("parent"),
        details=data,
    )
