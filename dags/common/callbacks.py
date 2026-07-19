"""Airflow callbacks and local log-based notification abstraction."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from src.orchestration.config import mask_secrets
from src.orchestration.monitoring import failure_record

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class LogNotificationService:
    """Emit notifications to task logs without external credentials."""

    def notify(self, event: str, payload: dict[str, Any]) -> None:
        """Log a security-filtered notification payload."""
        LOGGER.info(
            "Pipeline notification event=%s payload=%s",
            event,
            mask_secrets(str(payload)),
        )


def on_task_failure(context: dict[str, Any]) -> None:
    """Persist task failure evidence without masking the original error."""
    try:
        task_instance = context.get("task_instance")
        dag_run = context.get("dag_run")
        conf = getattr(dag_run, "conf", {}) or {}
        path = failure_record(
            dag_id=getattr(dag_run, "dag_id", "unknown"),
            dag_run_id=getattr(dag_run, "run_id", "unknown"),
            task_id=getattr(task_instance, "task_id", "unknown"),
            attempt=int(getattr(task_instance, "try_number", 1)),
            exception=context.get("exception"),
            batch_id=conf.get("batch_id"),
            log_url=getattr(task_instance, "log_url", None),
        )
        LogNotificationService().notify(
            "TASK_FAILURE", {"failure_record": str(path)}
        )
    except Exception:
        LOGGER.exception("Failure callback could not publish diagnostics")


def on_task_retry(context: dict[str, Any]) -> None:
    """Log one task-level recovery attempt."""
    task_instance = context.get("task_instance")
    LogNotificationService().notify("TASK_RETRY", {
        "task_id": getattr(task_instance, "task_id", "unknown"),
        "attempt": getattr(task_instance, "try_number", None),
    })


def on_task_success(context: dict[str, Any]) -> None:
    """Log successful task completion."""
    task_instance = context.get("task_instance")
    LogNotificationService().notify("TASK_SUCCESS", {
        "task_id": getattr(task_instance, "task_id", "unknown")
    })
