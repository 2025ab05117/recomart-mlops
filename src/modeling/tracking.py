"""MLflow experiment logging with local fallback."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import mlflow

from src.modeling.config import ModelingConfig
from src.modeling.errors import MLflowTrackingError


def configure_mlflow(config: ModelingConfig) -> None:
    """Configure the requested URI, resolving relative local storage."""
    tracking = config.tracking_uri
    if "://" not in tracking:
        os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
        tracking = (config.root / tracking).resolve().as_uri()
    mlflow.set_tracking_uri(tracking)
    mlflow.set_experiment(config.experiment_name)


def log_experiment(
    config: ModelingConfig,
    *,
    run_name: str,
    parameters: dict[str, Any],
    metrics: dict[str, float],
    artifacts: list[Path],
    tags: dict[str, str],
) -> dict[str, str]:
    """Log parameters, finite metrics, and artifacts to MLflow."""
    try:
        with mlflow.start_run(run_name=run_name, tags=tags) as run:
            mlflow.log_params({
                key: value for key, value in parameters.items()
                if value is not None
            })
            mlflow.log_metrics({
                key: value for key, value in metrics.items()
                if isinstance(value, (int, float))
                and value == value and abs(value) != float("inf")
            })
            config_path = Path(run.info.artifact_uri.replace("file:///", ""))
            for artifact in artifacts:
                mlflow.log_artifact(str(artifact))
            return {
                "run_id": run.info.run_id,
                "experiment_id": run.info.experiment_id,
                "artifact_uri": run.info.artifact_uri,
            }
    except Exception as exc:
        raise MLflowTrackingError("Unable to log MLflow experiment.") from exc


