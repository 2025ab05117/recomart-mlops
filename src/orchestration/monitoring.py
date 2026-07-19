"""Durable pipeline summaries, task tables, and assignment evidence."""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.orchestration.errors import PipelineSummaryError

ROOT = Path(__file__).resolve().parents[2]


def safe_identifier(value: str) -> str:
    """Convert an Airflow identifier into a portable partition value."""
    return re.sub(r"[^A-Za-z0-9_.=-]+", "_", value).strip("_") or "unknown"


def build_pipeline_summary(
    *,
    context: dict[str, Any],
    dag_id: str,
    dag_run_id: str,
    stages: dict[str, dict[str, Any]],
    task_instances: Iterable[dict[str, Any]] = (),
    status: str = "SUCCESS",
    error: str | None = None,
    output_root: Path | None = None,
) -> dict[str, Any]:
    """Aggregate lightweight stage contracts and write four evidence files."""
    completed = datetime.now(timezone.utc)
    started = datetime.fromisoformat(
        context["started_at"].replace("Z", "+00:00")
    )
    summary = {
        "pipeline_run_id": context["pipeline_run_id"],
        "dag_id": dag_id,
        "dag_run_id": dag_run_id,
        "status": status,
        "batch_id": _first(stages, "batch_id") or context.get("batch_id"),
        "feature_batch_id": _first(stages, "feature_batch_id"),
        "model_run_id": _first(stages, "model_run_id"),
        "mlflow_run_ids": (
            stages.get("modeling", {}).get("mlflow_run_ids", [])
        ),
        "started_at": context["started_at"],
        "completed_at": completed.isoformat().replace("+00:00", "Z"),
        "duration_seconds": round((completed - started).total_seconds(), 3),
        "stages": stages,
        "reports": {
            name: result.get("report_path")
            for name, result in stages.items()
            if result.get("report_path")
        },
        "errors": [error] if error else [],
    }
    directory = (
        output_root or ROOT / "reports/orchestration"
    ) / f"dag_run_id={safe_identifier(dag_run_id)}"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        _json(directory / "pipeline_run_summary.json", summary)
        tasks = list(task_instances)
        _task_csv(directory / "task_execution_summary.csv", tasks)
        (directory / "orchestration_report.md").write_text(
            _markdown(summary, tasks), encoding="utf-8"
        )
        (directory / "execution_evidence.txt").write_text(
            _evidence(summary, tasks), encoding="utf-8"
        )
    except OSError as exc:
        raise PipelineSummaryError(
            f"Unable to publish orchestration evidence under {directory}"
        ) from exc
    summary["output_directory"] = str(directory)
    return summary


def failure_record(
    *,
    dag_id: str,
    dag_run_id: str,
    task_id: str,
    attempt: int,
    exception: BaseException | None,
    batch_id: str | None,
    log_url: str | None,
    output_root: Path | None = None,
) -> Path:
    """Write a structured callback failure record without exposing secrets."""
    directory = (
        output_root or ROOT / "reports/orchestration/failures"
    ) / f"dag_run_id={safe_identifier(dag_run_id)}"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{safe_identifier(task_id)}_failure.json"
    _json(path, {
        "dag_id": dag_id,
        "dag_run_id": dag_run_id,
        "task_id": task_id,
        "execution_timestamp": datetime.now(timezone.utc).isoformat(),
        "attempt": attempt,
        "exception_type": (
            type(exception).__name__ if exception else None
        ),
        "exception_message": str(exception) if exception else None,
        "batch_id": batch_id,
        "log_url": log_url,
    })
    return path


def _first(stages: dict[str, dict[str, Any]], key: str) -> Any:
    for result in reversed(list(stages.values())):
        if result.get(key) is not None:
            return result[key]
    return None


def _json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, default=str, allow_nan=False),
        encoding="utf-8",
    )


def _task_csv(path: Path, tasks: list[dict[str, Any]]) -> None:
    fields = (
        "task_id", "state", "started_at", "ended_at",
        "duration_seconds", "retry_count",
    )
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for item in tasks:
            writer.writerow({field: item.get(field) for field in fields})


def _markdown(
    summary: dict[str, Any], tasks: list[dict[str, Any]]
) -> str:
    lines = [
        "# RecoMart Orchestration Report",
        "",
        f"- DAG: `{summary['dag_id']}`",
        f"- DAG run: `{summary['dag_run_id']}`",
        f"- Status: **{summary['status']}**",
        f"- Batch: `{summary.get('batch_id')}`",
        f"- Feature batch: `{summary.get('feature_batch_id')}`",
        f"- Model run: `{summary.get('model_run_id')}`",
        f"- Duration: {summary['duration_seconds']} seconds",
        "",
        "| Task | Status | Duration (s) | Retries |",
        "|---|---:|---:|---:|",
    ]
    lines.extend(
        f"| {item.get('task_id')} | {item.get('state')} | "
        f"{item.get('duration_seconds')} | {item.get('retry_count')} |"
        for item in tasks
    )
    return "\n".join(lines) + "\n"


def _evidence(
    summary: dict[str, Any], tasks: list[dict[str, Any]]
) -> str:
    lines = [
        f"DAG ID: {summary['dag_id']}",
        f"DAG Run ID: {summary['dag_run_id']}",
        f"Execution date: {summary['started_at']}",
        f"Overall status: {summary['status']}",
        f"Batch ID: {summary.get('batch_id')}",
        f"Feature batch ID: {summary.get('feature_batch_id')}",
        f"Model run ID: {summary.get('model_run_id')}",
        "MLflow run IDs: " + ", ".join(summary["mlflow_run_ids"]),
        f"Total duration seconds: {summary['duration_seconds']}",
        "Tasks:",
    ]
    lines.extend(
        f"- {item.get('task_id')}: {item.get('state')} "
        f"(duration={item.get('duration_seconds')}s, "
        f"retries={item.get('retry_count')})"
        for item in tasks
    )
    lines.append(f"Reports: {json.dumps(summary['reports'], default=str)}")
    return "\n".join(lines) + "\n"
