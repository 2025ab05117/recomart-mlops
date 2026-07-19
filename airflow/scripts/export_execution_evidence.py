"""Enrich a completed run's evidence with authoritative Airflow task states."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from src.orchestration.monitoring import safe_identifier


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export completed RecoMart Airflow task evidence."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--dag-id", default="recomart_end_to_end_pipeline"
    )
    parser.add_argument(
        "--report-root", type=Path, default=Path("reports/orchestration")
    )
    return parser


def _duration(start: str, end: str) -> float:
    return round(
        (
            datetime.fromisoformat(end)
            - datetime.fromisoformat(start)
        ).total_seconds(),
        3,
    )


def _retry_count(dag_id: str, run_id: str, task_id: str) -> int:
    log_root = Path(os.environ.get("AIRFLOW_HOME", "/opt/airflow")) / "logs"
    directory = (
        log_root / f"dag_id={dag_id}" / f"run_id={run_id}"
        / f"task_id={task_id}"
    )
    return max(0, len(list(directory.glob("attempt=*.log"))) - 1)


def main() -> int:
    """Query Airflow and enrich the already-generated summary artifacts."""
    args = _parser().parse_args()
    completed = subprocess.run(
        [
            "airflow", "tasks", "states-for-dag-run",
            args.dag_id, args.run_id, "--output", "json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    tasks: list[dict[str, Any]] = json.loads(completed.stdout)
    rows = [{
        "task_id": item["task_id"],
        "state": item["state"],
        "started_at": item["start_date"],
        "ended_at": item["end_date"],
        "duration_seconds": _duration(
            item["start_date"], item["end_date"]
        ),
        "retry_count": _retry_count(
            args.dag_id, args.run_id, item["task_id"]
        ),
    } for item in tasks]
    directory = (
        args.report_root / f"dag_run_id={safe_identifier(args.run_id)}"
    )
    summary_path = directory / "pipeline_run_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    summary["task_execution"] = rows
    summary_path.write_text(
        json.dumps(summary, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    with (directory / "task_execution_summary.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        f"DAG ID: {summary['dag_id']}",
        f"DAG Run ID: {summary['dag_run_id']}",
        f"Execution date: {summary['started_at']}",
        f"Overall status: {summary['status']}",
        f"Batch ID: {summary['batch_id']}",
        f"Feature batch ID: {summary['feature_batch_id']}",
        f"Model run ID: {summary['model_run_id']}",
        "MLflow run IDs: " + ", ".join(summary["mlflow_run_ids"]),
        f"Total duration seconds: {summary['duration_seconds']}",
        "Tasks:",
    ]
    lines.extend(
        f"- {row['task_id']}: {row['state']} "
        f"(duration={row['duration_seconds']}s, "
        f"retries={row['retry_count']})"
        for row in rows
    )
    lines.append(
        "Reports: " + json.dumps(summary["reports"], separators=(",", ":"))
    )
    (directory / "execution_evidence.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
