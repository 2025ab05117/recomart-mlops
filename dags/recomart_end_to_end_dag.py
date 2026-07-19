"""Production-style orchestration DAG for the complete RecoMart pipeline."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from airflow.sdk import DAG, Param, get_current_context, task
    from airflow.providers.standard.operators.empty import EmptyOperator
except ImportError:  # Airflow 2 compatibility for project consumers.
    from airflow import DAG
    from airflow.decorators import get_current_context, task
    from airflow.models.param import Param
    from airflow.operators.empty import EmptyOperator

from dags.common.callbacks import (
    on_task_failure,
    on_task_retry,
    on_task_success,
)
from src.orchestration.config import resolve_runtime_config
from src.orchestration.gates import enforce_quality_gate, verify_feature_store
from src.orchestration.monitoring import build_pipeline_summary
from src.orchestration.stages import (
    engineer_and_store_features,
    finalize_model_lineage,
    generate_source_data,
    ingest_raw_data,
    prepare_data,
    register_data_versions,
    train_and_evaluate_models,
    validate_data,
)

LOGGER = logging.getLogger(__name__)
DAG_ID = "recomart_end_to_end_pipeline"

DEFAULT_ARGS = {
    "owner": "recomart-mlops",
    "depends_on_past": False,
    "on_failure_callback": on_task_failure,
    "on_retry_callback": on_task_retry,
    "on_success_callback": on_task_success,
}

PARAMS = {
    "run_generator": Param(True, type="boolean"),
    "batch_id": Param(None, type=["null", "string"]),
    "storage": Param("local", enum=["local", "s3"]),
    "database_url_source": Param("environment", type="string"),
    "source_split": Param("train", enum=["train", "all"]),
    "run_eda": Param(True, type="boolean"),
    "run_versioning": Param(True, type="boolean"),
    "train_algorithm": Param(
        "all", enum=["all", "collaborative", "content"]
    ),
    "top_k": Param(10, type="integer", minimum=1),
    "strict_quality": Param(False, type="boolean"),
}


def _runtime_conf() -> tuple[dict[str, Any], str]:
    airflow_context = get_current_context()
    dag_run = airflow_context["dag_run"]
    supplied = {**dict(airflow_context["params"]), **(dag_run.conf or {})}
    return supplied, dag_run.run_id


def _task_rows(dag_run: Any) -> list[dict[str, Any]]:
    rows = []
    for instance in dag_run.get_task_instances():
        started = getattr(instance, "start_date", None)
        ended = getattr(instance, "end_date", None)
        duration = (
            (ended - started).total_seconds()
            if started is not None and ended is not None else None
        )
        rows.append({
            "task_id": instance.task_id,
            "state": str(instance.state),
            "started_at": started,
            "ended_at": ended,
            "duration_seconds": duration,
            "retry_count": max(0, int(instance.try_number or 1) - 1),
        })
    return rows


with DAG(
    dag_id=DAG_ID,
    description="End-to-end RecoMart recommendation data and ML pipeline",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
    schedule=os.environ.get("RECOMART_PIPELINE_SCHEDULE") or None,
    catchup=False,
    max_active_runs=1,
    params=PARAMS,
    tags=["recomart", "mlops", "recommendation", "assignment"],
) as dag:
    start_pipeline = EmptyOperator(task_id="start_pipeline")

    @task(
        task_id="validate_runtime_configuration",
        retries=0,
        execution_timeout=timedelta(minutes=5),
    )
    def runtime_configuration_task() -> dict[str, Any]:
        supplied, dag_run_id = _runtime_conf()
        result = resolve_runtime_config(supplied, dag_run_id=dag_run_id)
        LOGGER.info(
            "Runtime configuration validated pipeline_run_id=%s dag_run_id=%s",
            result["pipeline_run_id"], dag_run_id,
        )
        return result

    @task(
        task_id="generate_source_data",
        retries=1,
        retry_delay=timedelta(minutes=1),
        execution_timeout=timedelta(minutes=10),
    )
    def generation_task(context: dict[str, Any]) -> dict[str, Any]:
        return generate_source_data(context)

    @task(
        task_id="ingest_raw_data",
        retries=2,
        retry_delay=timedelta(minutes=2),
        execution_timeout=timedelta(minutes=15),
    )
    def ingestion_task(context: dict[str, Any]) -> dict[str, Any]:
        return ingest_raw_data(context)

    @task(
        task_id="validate_data",
        retries=1,
        execution_timeout=timedelta(minutes=20),
    )
    def validation_task(
        context: dict[str, Any], ingestion: dict[str, Any]
    ) -> dict[str, Any]:
        return validate_data(context, ingestion)

    @task(
        task_id="check_data_quality",
        retries=0,
        execution_timeout=timedelta(minutes=5),
    )
    def quality_task(
        context: dict[str, Any], validation: dict[str, Any]
    ) -> dict[str, Any]:
        return enforce_quality_gate(
            validation, strict_quality=context["strict_quality"]
        )

    @task(
        task_id="prepare_data",
        retries=1,
        execution_timeout=timedelta(minutes=30),
    )
    def preparation_task(
        context: dict[str, Any],
        validation: dict[str, Any],
        quality: dict[str, Any],
    ) -> dict[str, Any]:
        del quality
        return prepare_data(context, validation)

    @task(
        task_id="engineer_and_store_features",
        retries=1,
        execution_timeout=timedelta(minutes=45),
    )
    def feature_task(
        context: dict[str, Any], preparation: dict[str, Any]
    ) -> dict[str, Any]:
        return engineer_and_store_features(context, preparation)

    @task(
        task_id="verify_feature_store",
        retries=0,
        execution_timeout=timedelta(minutes=5),
    )
    def feature_gate_task(feature: dict[str, Any]) -> dict[str, Any]:
        return verify_feature_store(feature)

    @task(
        task_id="register_data_versions",
        retries=1,
        execution_timeout=timedelta(minutes=15),
    )
    def versioning_task(
        context: dict[str, Any],
        feature: dict[str, Any],
        gate: dict[str, Any],
    ) -> dict[str, Any]:
        del gate
        return register_data_versions(context, feature)

    @task(
        task_id="train_and_evaluate_models",
        retries=1,
        retry_delay=timedelta(minutes=5),
        execution_timeout=timedelta(minutes=60),
    )
    def modeling_task(
        context: dict[str, Any],
        feature: dict[str, Any],
        versioning: dict[str, Any],
    ) -> dict[str, Any]:
        del versioning
        return train_and_evaluate_models(context, feature)

    @task(
        task_id="finalize_model_lineage",
        retries=1,
        execution_timeout=timedelta(minutes=15),
    )
    def lineage_task(
        context: dict[str, Any],
        feature: dict[str, Any],
        modeling: dict[str, Any],
    ) -> dict[str, Any]:
        return finalize_model_lineage(context, feature, modeling)

    @task(
        task_id="generate_pipeline_summary",
        retries=0,
        execution_timeout=timedelta(minutes=5),
    )
    def summary_task(
        context: dict[str, Any],
        ingestion: dict[str, Any],
        validation: dict[str, Any],
        preparation: dict[str, Any],
        feature: dict[str, Any],
        versioning: dict[str, Any],
        modeling: dict[str, Any],
        lineage: dict[str, Any],
    ) -> dict[str, Any]:
        current = get_current_context()
        dag_run = current["dag_run"]
        result = build_pipeline_summary(
            context=context,
            dag_id=DAG_ID,
            dag_run_id=dag_run.run_id,
            stages={
                "ingestion": ingestion,
                "validation": validation,
                "preparation": preparation,
                "feature_engineering": feature,
                "versioning": {**versioning, **lineage},
                "modeling": modeling,
            },
            task_instances=_task_rows(dag_run),
        )
        LOGGER.info(
            "Pipeline summary generated status=SUCCESS batch_id=%s "
            "feature_batch_id=%s model_run_id=%s mlflow_run_ids=%s",
            result["batch_id"], result["feature_batch_id"],
            result["model_run_id"], result["mlflow_run_ids"],
        )
        return {
            key: result[key] for key in (
                "pipeline_run_id", "status", "batch_id", "feature_batch_id",
                "model_run_id", "mlflow_run_ids", "duration_seconds",
                "output_directory",
            )
        }

    runtime = runtime_configuration_task()
    generated = generation_task(runtime)
    ingested = ingestion_task(runtime)
    validated = validation_task(runtime, ingested)
    quality = quality_task(runtime, validated)
    prepared = preparation_task(runtime, validated, quality)
    featured = feature_task(runtime, prepared)
    feature_gate = feature_gate_task(featured)
    versioned = versioning_task(runtime, featured, feature_gate)
    modeled = modeling_task(runtime, featured, versioned)
    finalized = lineage_task(runtime, featured, modeled)
    summarized = summary_task(
        runtime, ingested, validated, prepared, featured,
        versioned, modeled, finalized,
    )
    end_pipeline = EmptyOperator(task_id="end_pipeline")

    start_pipeline >> runtime >> generated >> ingested
    summarized >> end_pipeline
