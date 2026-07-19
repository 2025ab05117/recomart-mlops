"""Lightweight, JSON-safe contracts exchanged through Airflow XCom."""

from __future__ import annotations

from typing import Any, TypedDict


SUCCESS_STATUSES = {
    "SUCCESS",
    "COMPLETED_WITH_WARNINGS",
    "COMPLETED_WITH_QUALITY_ISSUES",
    "IDEMPOTENT_SUCCESS",
}


class PipelineContext(TypedDict):
    """Identifiers and runtime parameters shared by pipeline tasks."""

    pipeline_run_id: str
    airflow_dag_run_id: str
    correlation_id: str
    batch_id: str | None
    started_at: str
    run_generator: bool
    storage: str
    source_split: str
    run_eda: bool
    run_versioning: bool
    train_algorithm: str
    top_k: int
    strict_quality: bool


StageResult = dict[str, Any]


def is_success(status: object) -> bool:
    """Return whether a stage status is safe for downstream processing."""
    return str(status).upper() in SUCCESS_STATUSES
