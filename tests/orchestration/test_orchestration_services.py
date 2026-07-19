"""Unit tests for lightweight orchestration contracts and gates."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.orchestration.config import (
    mask_secrets,
    resolve_runtime_config,
)
from src.orchestration.errors import (
    FeatureStoreGateError,
    QualityGateError,
    RuntimeConfigurationError,
)
from src.orchestration.gates import enforce_quality_gate, verify_feature_store
from src.orchestration.manifests import find_manifest, read_json
from src.orchestration.monitoring import (
    build_pipeline_summary,
    failure_record,
)


def _context() -> dict:
    return resolve_runtime_config(
        {"run_generator": False},
        dag_run_id="manual__test",
        now=datetime(2026, 7, 19, tzinfo=timezone.utc),
    )


def test_runtime_configuration_generates_pipeline_identifiers() -> None:
    context = _context()
    assert context["pipeline_run_id"].startswith("PIPE_20260719_")
    assert context["airflow_dag_run_id"] == "manual__test"
    assert context["source_split"] == "train"


def test_supplied_batch_disables_generation_and_propagates() -> None:
    context = resolve_runtime_config(
        {
            "batch_id": "RECO_20260719_010203_ab12cd",
            "run_generator": True,
        },
        dag_run_id="manual__existing",
    )
    assert context["batch_id"] == "RECO_20260719_010203_ab12cd"
    assert context["run_generator"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("storage", "azure"),
        ("source_split", "future"),
        ("train_algorithm", "random"),
        ("top_k", 0),
        ("batch_id", "unsafe"),
    ],
)
def test_invalid_runtime_configuration(field: str, value: object) -> None:
    with pytest.raises(RuntimeConfigurationError):
        resolve_runtime_config({field: value}, dag_run_id="bad")


def test_quality_gate_allows_non_strict_quality_issues() -> None:
    result = enforce_quality_gate(
        {
            "status": "COMPLETED_WITH_QUALITY_ISSUES",
            "invalid_record_count": 4,
            "quality_score": 97.2,
        },
        strict_quality=False,
    )
    assert result["status"] == "SUCCESS"


def test_quality_gate_rejects_strict_quality_issues() -> None:
    with pytest.raises(QualityGateError):
        enforce_quality_gate(
            {
                "status": "COMPLETED_WITH_QUALITY_ISSUES",
                "invalid_record_count": 1,
            },
            strict_quality=True,
        )


def test_feature_store_gate_accepts_complete_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "feature_manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    result = verify_feature_store({
        "status": "IDEMPOTENT_SUCCESS",
        "feature_batch_id": "FEAT_1",
        "manifest_path": str(manifest),
        "database_engine": "sqlite",
        "row_counts": {
            "user_feature_count": 1,
            "item_feature_count": 1,
            "user_item_feature_count": 1,
        },
    })
    assert result["feature_batch_id"] == "FEAT_1"


def test_feature_store_gate_rejects_empty_required_table(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "feature_manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    with pytest.raises(FeatureStoreGateError):
        verify_feature_store({
            "status": "SUCCESS",
            "feature_batch_id": "FEAT_1",
            "manifest_path": str(manifest),
            "row_counts": {
                "user_feature_count": 1,
                "item_feature_count": 0,
                "user_item_feature_count": 1,
            },
        })


def test_manifest_parsing_and_batch_resolution(tmp_path: Path) -> None:
    target = (
        tmp_path / "batch_id=RECO_20260719_010203_ab12cd"
        / "validation_manifest.json"
    )
    target.parent.mkdir()
    target.write_text('{"status":"SUCCESS"}', encoding="utf-8")
    resolved = find_manifest(
        tmp_path, target.name, batch_id="RECO_20260719_010203_ab12cd"
    )
    assert read_json(resolved)["status"] == "SUCCESS"


def test_pipeline_summary_writes_all_evidence_files(tmp_path: Path) -> None:
    summary = build_pipeline_summary(
        context=_context(),
        dag_id="recomart_end_to_end_pipeline",
        dag_run_id="manual__test",
        stages={
            "ingestion": {"batch_id": "RECO_20260719_010203_ab12cd"},
            "modeling": {
                "feature_batch_id": "FEAT_1",
                "model_run_id": "MODEL_1",
                "mlflow_run_ids": ["mlflow-1"],
            },
        },
        task_instances=[{
            "task_id": "ingest_raw_data",
            "state": "success",
            "duration_seconds": 1.2,
            "retry_count": 0,
        }],
        output_root=tmp_path,
    )
    output = Path(summary["output_directory"])
    assert {
        path.name for path in output.iterdir()
    } == {
        "pipeline_run_summary.json",
        "task_execution_summary.csv",
        "orchestration_report.md",
        "execution_evidence.txt",
    }
    payload = json.loads(
        (output / "pipeline_run_summary.json").read_text(encoding="utf-8")
    )
    assert payload["model_run_id"] == "MODEL_1"


def test_failure_callback_record_contains_diagnostics(tmp_path: Path) -> None:
    path = failure_record(
        dag_id="dag", dag_run_id="manual/test", task_id="failed.task",
        attempt=2, exception=ValueError("bad input"), batch_id="RECO_1",
        log_url="http://localhost/log", output_root=tmp_path,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["exception_type"] == "ValueError"
    assert payload["attempt"] == 2


def test_credentials_are_masked() -> None:
    secret = "postgresql://user:password@localhost/db?token=abc"
    masked = mask_secrets(secret)
    assert "password" not in masked
    assert "abc" not in masked
    assert "***" in masked
