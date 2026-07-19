"""DagBag contract tests for the RecoMart orchestration graph."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

airflow_models = pytest.importorskip("airflow.models")
DagBag = airflow_models.DagBag


@pytest.fixture(scope="module")
def dag():
    root = Path(__file__).resolve().parents[2]
    bag = DagBag(dag_folder=str(root / "dags"), include_examples=False)
    assert not bag.import_errors
    return bag.dags["recomart_end_to_end_pipeline"]


def test_dag_import_and_runtime_policy(dag) -> None:
    assert dag is not None
    assert dag.catchup is False
    assert dag.max_active_runs == 1
    assert dag.schedule is None


def test_required_tasks_exist(dag) -> None:
    required = {
        "start_pipeline",
        "validate_runtime_configuration",
        "generate_source_data",
        "ingest_raw_data",
        "validate_data",
        "check_data_quality",
        "prepare_data",
        "engineer_and_store_features",
        "verify_feature_store",
        "register_data_versions",
        "train_and_evaluate_models",
        "finalize_model_lineage",
        "generate_pipeline_summary",
        "end_pipeline",
    }
    assert required <= set(dag.task_ids)


def test_dependency_order_and_gates(dag) -> None:
    assert "check_data_quality" in dag.get_task("prepare_data").upstream_task_ids
    assert "verify_feature_store" in (
        dag.get_task("register_data_versions").upstream_task_ids
    )
    assert "register_data_versions" in (
        dag.get_task("train_and_evaluate_models").upstream_task_ids
    )
    assert "train_and_evaluate_models" in (
        dag.get_task("finalize_model_lineage").upstream_task_ids
    )
    assert "finalize_model_lineage" in (
        dag.get_task("generate_pipeline_summary").upstream_task_ids
    )


def test_processing_tasks_have_finite_timeouts_and_retries(dag) -> None:
    for task_id in (
        "generate_source_data", "ingest_raw_data", "validate_data",
        "prepare_data", "engineer_and_store_features",
        "register_data_versions", "train_and_evaluate_models",
    ):
        task = dag.get_task(task_id)
        assert isinstance(task.execution_timeout, timedelta)
        assert task.retries >= 1


