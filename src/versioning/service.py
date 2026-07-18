"""Application service coordinating registration, lineage, and verification."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.versioning.checksums import verify_checksum
from src.versioning.config import VersioningConfig
from src.versioning.discovery import ArtifactObservation, discover_artifact
from src.versioning.errors import LineageError, RegistryError
from src.versioning.lineage import build_lineage, verify_lineage
from src.versioning.registry import (
    load_registry,
    registry_entry,
    select_version,
)
from src.versioning.visualization import render_lineage

LOGGER = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, value: Any) -> None:
    """Atomically write strict, portable JSON."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(value, indent=2, default=str, allow_nan=False),
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        raise RegistryError(f"Unable to write registry artifact: {path}") from exc


def _manifest_duration(path: Path) -> float | None:
    """Calculate transformation duration from existing UTC manifest times."""
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        started = datetime.fromisoformat(
            str(manifest["started_at"]).replace("Z", "+00:00")
        )
        completed = datetime.fromisoformat(
            str(manifest["completed_at"]).replace("Z", "+00:00")
        )
        return max(0.0, (completed - started).total_seconds())
    except (OSError, KeyError, ValueError, json.JSONDecodeError):
        return None


class VersioningService:
    """Register existing artifacts and build end-to-end immutable lineage."""

    def __init__(self, config: VersioningConfig) -> None:
        """Create a service using resolved external configuration."""
        self.config = config

    def observe(
        self, stages: Iterable[str], *, batch_id: str | None = None
    ) -> dict[str, ArtifactObservation]:
        """Discover requested stages using their authoritative manifests."""
        observations = {}
        for stage in stages:
            observation = discover_artifact(
                self.config, stage, batch_id=batch_id
            )
            observations[stage] = observation
            LOGGER.info("Checksum generated", extra={
                "dataset_name": stage,
                "batch_id": observation.batch_id,
                "operation": "checksum",
                "status": "SUCCESS",
                "checksum": observation.checksum,
            })
        return observations

    def register(
        self, *, stage: str | None = None, batch_id: str | None = None
    ) -> dict[str, Any]:
        """Register all or one artifact, reusing versions by checksum."""
        stages = [stage] if stage else list(self.config.artifacts)
        observations = self.observe(stages, batch_id=batch_id)
        registry = load_registry(self.config.registry_path)
        entries = list(registry.get("datasets", []))
        current = {
            item["dataset_name"]: item
            for item in entries
            if item.get("is_current", True)
        }
        for stage_name in stages:
            observation = observations[stage_name]
            version, created = select_version(
                registry, observation, self.config.versions[stage_name]
            )
            parent = current.get(observation.parent_name or "")
            parent_version = (
                parent["dataset_version"] if parent is not None else None
            )
            entry = registry_entry(
                observation,
                dataset_version=version,
                parent_dataset_version=parent_version,
                created_by=self.config.created_by,
            )
            entry["is_current"] = True
            if created:
                for existing in entries:
                    if existing["dataset_name"] == stage_name:
                        existing["is_current"] = False
                entries.append(entry)
                LOGGER.info("Version created", extra={
                    "dataset_name": stage_name,
                    "dataset_version": version,
                    "batch_id": observation.batch_id,
                    "operation": "register",
                    "status": "SUCCESS",
                    "checksum": observation.checksum,
                })
            else:
                current_entry = next(
                    item for item in entries
                    if item["dataset_name"] == stage_name
                    and item["dataset_version"] == version
                )
                current_entry.update(entry)
            current[stage_name] = entry
        registry.update({
            "registry_schema_version": self.config.schema_version,
            "generated_at": _now(),
            "configuration_hash": self.config.sha256,
            "datasets": entries,
        })
        _write_json(self.config.registry_path, registry)
        LOGGER.info("Registry updated", extra={
            "operation": "registry",
            "status": "SUCCESS",
        })
        return registry

    def generate_lineage(self) -> dict[str, Any]:
        """Generate JSON lineage and PNG visualization from current versions."""
        registry = load_registry(self.config.registry_path)
        current = {
            item["dataset_name"]: item
            for item in registry.get("datasets", [])
            if item.get("is_current")
        }
        missing = set(self.config.artifacts) - set(current)
        if missing:
            raise LineageError(
                f"Current registry is missing stages: {sorted(missing)}"
            )
        model_manifest = self.config.root / current["models"]["manifest_path"]
        model_details = json.loads(model_manifest.read_text(encoding="utf-8"))
        transformations = {
            name: str(value["transformation"])
            for name, value in self.config.artifacts.items()
        }
        report = build_lineage(
            current, transformations, model_details=model_details
        )
        by_version = {
            item["dataset_version"]: item for item in current.values()
        }
        for edge in report["pipeline_graph"]["edges"]:
            parent = by_version.get(edge["parent_version"], {})
            child = by_version.get(edge["child_version"], {})
            edge["records_in"] = parent.get("record_count")
            edge["records_out"] = child.get("record_count", 1)
            edge["configuration_used"] = child.get(
                "configuration_hash", parent.get("configuration_hash", "")
            )
            edge["execution_time_seconds"] = _manifest_duration(
                self.config.root / edge["manifest"]
            )
        errors = verify_lineage(report)
        if errors:
            raise LineageError("; ".join(errors))
        _write_json(self.config.lineage_path, report)
        render_lineage(report, self.config.graph_path)
        LOGGER.info("Lineage updated", extra={
            "operation": "lineage",
            "status": "SUCCESS",
        })
        return report

    def generate_summary(
        self, lineage: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Write current versions and DVC-compatible scalar metrics."""
        registry = load_registry(self.config.registry_path)
        current = {
            item["dataset_name"]: item
            for item in registry.get("datasets", [])
            if item.get("is_current")
        }
        report = lineage or json.loads(
            self.config.lineage_path.read_text(encoding="utf-8")
        )
        summary = {
            "generated_at": _now(),
            "current_dataset_versions": {
                name: item["dataset_version"] for name, item in current.items()
            },
            "current_feature_version": current["features"]["dataset_version"],
            "current_model_version": current["models"]["dataset_version"],
            "current_batch": current["models"]["batch_id"],
            "checksums": {
                name: item["checksum"] for name, item in current.items()
            },
            "storage_locations": {
                name: item["storage_location"] for name, item in current.items()
            },
            "parent_versions": {
                name: item["parent_dataset_version"]
                for name, item in current.items()
            },
        }
        _write_json(self.config.summary_path, summary)
        metrics = {
            "registered_dataset_versions": len(registry.get("datasets", [])),
            "current_artifacts": len(current),
            "lineage_edges": len(
                report.get("pipeline_graph", {}).get("edges", [])
            ),
            "verification_failures": 0,
        }
        _write_json(self.config.metrics_path, metrics)
        return summary

    def verify(self, *, stage: str | None = None) -> dict[str, Any]:
        """Verify manifests, checksums, semantic versions, and lineage."""
        registry = load_registry(self.config.registry_path)
        selected = [
            item for item in registry.get("datasets", [])
            if item.get("is_current")
            and (stage is None or item["dataset_name"] == stage)
        ]
        results = []
        failures = []
        for item in selected:
            location = self.config.root / item["storage_location"]
            manifest = self.config.root / item["manifest_path"]
            checksum_valid = verify_checksum(location, item["checksum"])
            manifest_valid = verify_manifest(manifest)
            valid = checksum_valid and manifest_valid
            result = {
                "dataset_name": item["dataset_name"],
                "dataset_version": item["dataset_version"],
                "checksum_valid": checksum_valid,
                "manifest_valid": manifest_valid,
                "status": "PASSED" if valid else "FAILED",
            }
            results.append(result)
            if not valid:
                failures.append(item["dataset_name"])
        lineage_errors = []
        if self.config.lineage_path.exists():
            lineage_errors = verify_lineage(json.loads(
                self.config.lineage_path.read_text(encoding="utf-8")
            ))
        failures.extend(lineage_errors)
        LOGGER.info("Verification complete", extra={
            "operation": "verify",
            "status": "SUCCESS" if not failures else "FAILED",
        })
        return {
            "status": "SUCCESS" if not failures else "FAILED",
            "datasets": results,
            "lineage_errors": lineage_errors,
            "failures": failures,
        }


def verify_manifest(path: Path) -> bool:
    """Return whether a linked manifest exists and contains valid JSON."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return isinstance(value, dict) and bool(value)
    except (OSError, json.JSONDecodeError):
        return False


def verify_dataset_version(
    config: VersioningConfig, dataset_version: str
) -> bool:
    """Verify one registered dataset version by identity and checksum."""
    registry = load_registry(config.registry_path)
    item = next(
        (
            value for value in registry.get("datasets", [])
            if value["dataset_version"] == dataset_version
        ),
        None,
    )
    if item is None:
        return False
    return (
        verify_manifest(config.root / item["manifest_path"])
        and verify_checksum(
            config.root / item["storage_location"], item["checksum"]
        )
    )

