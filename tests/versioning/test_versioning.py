"""Unit and focused integration tests for data versioning and lineage."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from src.versioning.checksums import (
    sha256_artifact,
    sha256_file,
    verify_checksum,
)
from src.versioning.cli import main
from src.versioning.config import load_versioning_config
from src.versioning.discovery import ArtifactObservation
from src.versioning.lineage import build_lineage, verify_lineage
from src.versioning.registry import (
    registry_entry,
    select_version,
)
from src.versioning.service import verify_manifest


def observation(checksum: str = "a" * 64) -> ArtifactObservation:
    """Build a complete deterministic observed artifact."""
    return ArtifactObservation(
        dataset_name="raw",
        pipeline_stage="raw",
        batch_id="RECO_TEST",
        run_id="run-1",
        created_at="2026-07-19T00:00:00Z",
        checksum=checksum,
        record_count=3,
        schema_version="1.0",
        storage_location="data/raw",
        manifest_path="data/raw/ingestion_manifest.json",
        configuration_hash="b" * 64,
        transformation="ingestion",
        parent_name="incoming",
        details={},
    )


def test_file_and_directory_checksum_are_deterministic(tmp_path: Path) -> None:
    """Checksums must change with content and be stable otherwise."""
    directory = tmp_path / "artifact"
    directory.mkdir()
    first = directory / "a.txt"
    first.write_text("one", encoding="utf-8")
    checksum = sha256_artifact(directory)
    assert checksum == sha256_artifact(directory)
    assert sha256_file(first)
    assert verify_checksum(directory, checksum)
    first.write_text("two", encoding="utf-8")
    assert not verify_checksum(directory, checksum)


def test_semantic_version_reuse_and_patch_increment() -> None:
    """Matching checksums reuse a version; changed data increments patch."""
    existing = {
        "datasets": [{
            "dataset_name": "raw",
            "dataset_version": "raw-v1.0.0",
            "checksum": "a" * 64,
        }]
    }
    assert select_version(existing, observation(), "1.0.0") == (
        "raw-v1.0.0", False
    )
    assert select_version(
        existing, observation("c" * 64), "1.0.0"
    ) == ("raw-v1.0.1", True)


def test_registry_entry_contains_required_metadata() -> None:
    """Registration must persist every required traceability field."""
    entry = registry_entry(
        observation(),
        dataset_version="raw-v1.0.0",
        parent_dataset_version="incoming-v1.0.0",
        created_by="test",
    )
    required = {
        "dataset_version", "dataset_name", "batch_id", "pipeline_stage",
        "created_at", "checksum", "record_count", "schema_version",
        "parent_dataset_version", "parent_batch", "created_by",
        "storage_location", "manifest_path", "configuration_hash",
    }
    assert required <= set(entry)


def test_lineage_builds_acyclic_graph_and_mlflow_edge() -> None:
    """Lineage should connect parent, model, and terminal MLflow run."""
    incoming = registry_entry(
        observation(),
        dataset_version="incoming-v1.0.0",
        parent_dataset_version=None,
        created_by="test",
    )
    incoming.update(dataset_name="incoming", pipeline_stage="incoming")
    model = dict(incoming)
    model.update(
        dataset_name="models",
        pipeline_stage="models",
        dataset_version="models-v1.0.0",
        parent_dataset_version="incoming-v1.0.0",
    )
    report = build_lineage(
        {"incoming": incoming, "models": model},
        {"incoming": "generate", "models": "train"},
        model_details={
            "training_batch_id": "RECO_TEST",
            "completed_at": "2026-07-19T00:00:00Z",
            "models": {
                "collaborative": {
                    "mlflow": {
                        "run_id": "abc123",
                        "artifact_uri": "file:///mlruns/abc123",
                    }
                }
            },
        },
    )
    assert verify_lineage(report) == []
    assert any(
        edge["child_version"] == "mlflow-run:abc123"
        for edge in report["pipeline_graph"]["edges"]
    )


def _write_fixture_project(root: Path) -> Path:
    (root / "configs").mkdir()
    (root / "data/incoming").mkdir(parents=True)
    (root / "data/raw/manifests").mkdir(parents=True)
    (root / "data/incoming/users.csv").write_text(
        "user_id\n1\n", encoding="utf-8"
    )
    manifest = {
        "manifest_version": "1.0",
        "batch_id": "RECO_TEST",
        "run_id": "run-test",
        "completed_at": "2026-07-19T00:00:00Z",
        "status": "SUCCESS",
        "files": [{"record_count": 1, "status": "SUCCESS"}],
    }
    manifest_path = root / "data/raw/manifests/ingestion_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    config = {
        "versioning": {
            "schema_version": "1.0",
            "created_by": "test",
            "registry_path": "reports/versioning/dataset_registry.json",
            "lineage_path": "reports/versioning/lineage_report.json",
            "summary_path": "reports/versioning/version_summary.json",
            "metrics_path": "reports/versioning/dvc_metrics.json",
            "graph_path": "reports/versioning/pipeline_lineage.png",
            "stage_snapshot_path": "reports/versioning/stages",
        },
        "versions": {"incoming": "1.0.0"},
        "artifacts": {
            "incoming": {
                "location": "data/incoming",
                "parent": None,
                "transformation": "generate",
            }
        },
        "logging": {
            "level": "INFO",
            "directory": "logs/versioning",
            "filename": "versioning.log",
            "max_bytes": 100000,
            "backup_count": 1,
        },
    }
    config_path = root / "configs/versioning.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return config_path


def test_cli_registration_and_verification(tmp_path: Path) -> None:
    """CLI should register manifest linkage and verify the resulting checksum."""
    config_path = _write_fixture_project(tmp_path)
    assert main([
        "--config", str(config_path), "--stage", "incoming", "--register"
    ]) == 0
    assert main([
        "--config", str(config_path), "--stage", "incoming", "--verify"
    ]) == 0
    registry_path = tmp_path / "reports/versioning/dataset_registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert registry["datasets"][0]["manifest_path"].endswith(
        "ingestion_manifest.json"
    )


def test_manifest_verification_and_dvc_pipeline_assets(tmp_path: Path) -> None:
    """Manifest verification and checked-in DVC definitions should be valid."""
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"status": "SUCCESS"}', encoding="utf-8")
    assert verify_manifest(manifest)
    root = Path(__file__).resolve().parents[2]
    pipeline = yaml.safe_load((root / "dvc.yaml").read_text(encoding="utf-8"))
    assert list(pipeline["stages"]) == [
        "generator", "ingestion", "validation", "preparation",
        "feature_engineering", "training", "registry_and_lineage",
    ]
    assert (root / ".dvc/config").exists()
    assert (root / ".dvcignore").exists()


def test_configuration_resolves_paths(tmp_path: Path) -> None:
    """Versioning configuration paths must be repository-root-relative."""
    config_path = _write_fixture_project(tmp_path)
    config = load_versioning_config(config_path, project_root=tmp_path)
    assert config.registry_path == (
        tmp_path / "reports/versioning/dataset_registry.json"
    ).resolve()
