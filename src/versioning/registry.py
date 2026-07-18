"""Immutable semantic dataset-version registry persistence."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.versioning.discovery import ArtifactObservation
from src.versioning.errors import RegistryError

SEMVER = re.compile(r"^(?P<name>[a-z_]+)-v(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)$")


def load_registry(path: Path) -> dict[str, Any]:
    """Read an existing registry or return an empty versioned document."""
    if not path.exists():
        return {
            "registry_schema_version": "1.0",
            "generated_at": None,
            "datasets": [],
        }
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"Unable to read dataset registry: {path}") from exc


def select_version(
    registry: dict[str, Any],
    observation: ArtifactObservation,
    base_version: str,
) -> tuple[str, bool]:
    """Reuse a checksum version or increment the configured semantic patch."""
    matches = [
        item for item in registry.get("datasets", [])
        if item["dataset_name"] == observation.dataset_name
    ]
    for item in matches:
        if item["checksum"] == observation.checksum:
            return str(item["dataset_version"]), False
    if not matches:
        return f"{observation.dataset_name}-v{base_version}", True
    parsed = [
        SEMVER.match(str(item["dataset_version"])) for item in matches
    ]
    versions = [
        (int(match["major"]), int(match["minor"]), int(match["patch"]))
        for match in parsed if match
    ]
    if not versions:
        raise RegistryError(
            f"Invalid semantic version for {observation.dataset_name}"
        )
    major, minor, patch = max(versions)
    return f"{observation.dataset_name}-v{major}.{minor}.{patch + 1}", True


def registry_entry(
    observation: ArtifactObservation,
    *,
    dataset_version: str,
    parent_dataset_version: str | None,
    created_by: str,
) -> dict[str, Any]:
    """Build the complete required metadata record for one artifact."""
    return {
        "dataset_version": dataset_version,
        "dataset_name": observation.dataset_name,
        "batch_id": observation.batch_id,
        "run_id": observation.run_id,
        "pipeline_stage": observation.pipeline_stage,
        "created_at": observation.created_at,
        "checksum": observation.checksum,
        "record_count": observation.record_count,
        "schema_version": observation.schema_version,
        "parent_dataset_version": parent_dataset_version,
        "parent_batch": (
            observation.batch_id if parent_dataset_version else None
        ),
        "created_by": created_by,
        "storage_location": observation.storage_location,
        "manifest_path": observation.manifest_path,
        "configuration_hash": observation.configuration_hash,
    }
