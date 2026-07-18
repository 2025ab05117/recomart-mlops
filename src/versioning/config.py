"""Typed external configuration for versioning."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.versioning.errors import VersioningError


@dataclass(frozen=True)
class VersioningConfig:
    """Resolved configuration and immutable configuration identity."""

    root: Path
    path: Path
    sha256: str
    schema_version: str
    created_by: str
    registry_path: Path
    lineage_path: Path
    summary_path: Path
    metrics_path: Path
    graph_path: Path
    stage_snapshot_path: Path
    versions: dict[str, str]
    artifacts: dict[str, dict[str, Any]]
    log_level: str
    log_directory: Path
    log_filename: str
    log_max_bytes: int
    log_backup_count: int


def load_versioning_config(
    path: Path = Path("configs/versioning.yaml"),
    *,
    project_root: Path | None = None,
) -> VersioningConfig:
    """Load and validate versioning YAML without reading secrets."""
    if project_root is not None:
        root = project_root.resolve()
    elif path.is_absolute():
        root = path.resolve().parent.parent
    else:
        root = Path(__file__).resolve().parents[2]
    resolved = path if path.is_absolute() else root / path
    try:
        content = resolved.read_bytes()
        raw = yaml.safe_load(content)
        versioning = raw["versioning"]
        logging = raw["logging"]
        artifacts = raw["artifacts"]
        versions = raw["versions"]
    except (OSError, KeyError, TypeError, yaml.YAMLError) as exc:
        raise VersioningError(
            f"Unable to load versioning configuration: {resolved}"
        ) from exc

    def local(value: object) -> Path:
        candidate = Path(str(value))
        return (
            candidate.resolve()
            if candidate.is_absolute()
            else (root / candidate).resolve()
        )

    if set(artifacts) != set(versions):
        raise VersioningError(
            "Every configured artifact requires a semantic base version."
        )
    return VersioningConfig(
        root=root,
        path=resolved.resolve(),
        sha256=hashlib.sha256(content).hexdigest(),
        schema_version=str(versioning["schema_version"]),
        created_by=str(versioning["created_by"]),
        registry_path=local(versioning["registry_path"]),
        lineage_path=local(versioning["lineage_path"]),
        summary_path=local(versioning["summary_path"]),
        metrics_path=local(versioning["metrics_path"]),
        graph_path=local(versioning["graph_path"]),
        stage_snapshot_path=local(versioning["stage_snapshot_path"]),
        versions={key: str(value) for key, value in versions.items()},
        artifacts=artifacts,
        log_level=str(logging["level"]).upper(),
        log_directory=local(logging["directory"]),
        log_filename=str(logging["filename"]),
        log_max_bytes=int(logging["max_bytes"]),
        log_backup_count=int(logging["backup_count"]),
    )

