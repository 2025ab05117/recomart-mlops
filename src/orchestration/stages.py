"""Thin application-service adapters used by Airflow tasks.

This module deliberately contains no data transformations. It invokes the
existing stage runners and converts their durable manifests to small XCom
contracts.
"""

from __future__ import annotations

import logging
import math
from dataclasses import replace
from pathlib import Path
from typing import Any

from src.orchestration.contracts import is_success
from src.orchestration.errors import StageExecutionError
from src.orchestration.manifests import find_manifest, total_records

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]


def generate_source_data(context: dict[str, Any]) -> dict[str, Any]:
    """Run the existing deterministic generator when enabled."""
    if not context["run_generator"]:
        return {
            "status": "SKIPPED",
            "batch_id": context.get("batch_id"),
            "reason": "Existing batch reprocessing or generation disabled.",
        }
    from src.generator.batch_generator import BatchGenerator
    from src.generator.generator_config import GeneratorConfig

    config = GeneratorConfig.from_yaml(ROOT / "configs/generator.yaml")
    # A new pipeline run intentionally refreshes the incoming landing zone.
    result = BatchGenerator(
        replace(config, overwrite_existing=True)
    ).generate()
    return {
        "status": "SUCCESS",
        "batch_id": None,
        "output_path": str(result.output_directory),
        "record_counts": {
            "users": result.users_count,
            "products": result.products_count,
            "clickstream": result.clickstream_count,
            "purchasehistory": result.purchases_count,
            "popularity": result.popularity_count,
        },
    }


def ingest_raw_data(context: dict[str, Any]) -> dict[str, Any]:
    """Run manifest-producing file and REST ingestion."""
    from src.ingestion.cli import create_storage
    from src.ingestion.config import load_ingestion_config
    from src.ingestion.ingestion_runner import IngestionRunner

    config = load_ingestion_config(
        ROOT / "configs/ingestion.yaml",
        overrides={"storage": context["storage"]},
    )
    result = IngestionRunner(
        config=config, storage=create_storage(config)
    ).run(batch_id=context.get("batch_id"))
    manifest = result.manifest.to_dict()
    if not is_success(manifest["status"]):
        raise StageExecutionError(
            f"Ingestion failed; manifest={result.manifest_path}"
        )
    return {
        "batch_id": manifest["batch_id"],
        "ingestion_run_id": manifest["run_id"],
        "correlation_id": manifest["correlation_id"],
        "status": manifest["status"],
        "manifest_path": result.manifest_path,
        "raw_paths": [
            item["destination_path"] for item in manifest["files"]
            if item.get("destination_path")
        ],
        "record_count": total_records(manifest["files"]),
    }


def validate_data(
    context: dict[str, Any], ingestion: dict[str, Any]
) -> dict[str, Any]:
    """Run Pandas validation against the ingested batch manifest."""
    from src.validation.cli import create_repository
    from src.validation.config import load_validation_config
    from src.validation.validation_runner import ValidationRunner

    config = load_validation_config(ROOT / "configs/validation_rules.yaml")
    repository = create_repository(
        config=config,
        storage_type=context["storage"],
        bucket=None,
        prefix="raw",
        endpoint_url=None,
        region=None,
        profile=None,
    )
    result = ValidationRunner(
        config=config, repository=repository
    ).run(batch_id=ingestion["batch_id"])
    manifest = result.manifest.to_dict()
    manifest_path = find_manifest(
        config.report_path, "validation_manifest.json",
        batch_id=manifest["batch_id"],
    )
    invalid = sum(
        int(item.get("invalid_records", 0)) for item in manifest["datasets"]
    )
    return {
        "batch_id": manifest["batch_id"],
        "validation_run_id": manifest["validation_run_id"],
        "correlation_id": manifest["correlation_id"],
        "status": manifest["status"],
        "manifest_path": str(manifest_path),
        "quality_score": manifest["overall_quality_score"],
        "invalid_record_count": invalid,
        "record_count": sum(
            int(item.get("total_records", 0))
            for item in manifest["datasets"]
        ),
        "report_path": manifest["report_path"],
    }


def prepare_data(
    context: dict[str, Any], validation: dict[str, Any]
) -> dict[str, Any]:
    """Run preparation using validated data only."""
    from src.preparation.config import load_preparation_config
    from src.preparation.runner import PreparationRunner

    config = load_preparation_config(ROOT / "configs/preparation.yaml")
    manifest = PreparationRunner(config).run(
        batch_id=validation["batch_id"], run_eda=context["run_eda"]
    )
    manifest_path = find_manifest(
        config.output_path, "preparation_manifest.json",
        batch_id=manifest["batch_id"],
    )
    produced = manifest["records_produced"]
    return {
        "batch_id": manifest["batch_id"],
        "preparation_run_id": manifest["preparation_run_id"],
        "correlation_id": manifest["correlation_id"],
        "status": (
            "IDEMPOTENT_SUCCESS"
            if manifest.get("idempotent") else manifest["status"]
        ),
        "manifest_path": str(manifest_path),
        "prepared_path": str(manifest_path.parent),
        "prepared_interactions": produced["interactions_prepared"],
        "sparsity": manifest["matrix_statistics"]["sparsity"],
    }


def engineer_and_store_features(
    context: dict[str, Any], preparation: dict[str, Any]
) -> dict[str, Any]:
    """Compute features and persist the warehouse transactionally."""
    from src.feature_engineering.config import load_feature_config
    from src.feature_engineering.runner import FeatureRunner

    config = load_feature_config(
        ROOT / "configs/feature_engineering.yaml",
        overrides={"source_split": context["source_split"]},
    )
    manifest = FeatureRunner(config).run(
        batch_id=preparation["batch_id"], write_parquet=True
    )
    if manifest.get("status") == "IDEMPOTENT_SUCCESS":
        feature_id = manifest["feature_batch_id"]
        manifest_path = find_manifest(
            config.output_path, "feature_manifest.json"
        )
        stored = _load_json(manifest_path)
        row_counts = stored["row_counts"]
        summary_path = stored["feature_summary_path"]
        database_engine = stored["database_engine"]
    else:
        feature_id = manifest["feature_batch_id"]
        manifest_path = find_manifest(
            config.output_path, "feature_manifest.json"
        )
        row_counts = manifest["row_counts"]
        summary_path = manifest["feature_summary_path"]
        database_engine = manifest["database_engine"]
    return {
        "batch_id": preparation["batch_id"],
        "feature_batch_id": feature_id,
        "status": manifest["status"],
        "manifest_path": str(manifest_path),
        "feature_summary_path": summary_path,
        "database_engine": database_engine,
        "row_counts": row_counts,
        "source_split": context["source_split"],
    }


def register_data_versions(
    context: dict[str, Any], feature: dict[str, Any]
) -> dict[str, Any]:
    """Register existing manifests and generate lineage without duplicating it."""
    if not context["run_versioning"]:
        return {"status": "SKIPPED", "reason": "Versioning disabled."}
    from src.versioning.config import load_versioning_config
    from src.versioning.service import VersioningService

    config = load_versioning_config(ROOT / "configs/versioning.yaml")
    service = VersioningService(config)
    for stage in (
        "incoming", "raw", "validated", "prepared", "features", "eda_reports"
    ):
        service.register(stage=stage, batch_id=feature["batch_id"])
    return {
        "status": "SUCCESS",
        "registry_path": str(config.registry_path),
        "lineage_path": None,
        "summary_path": None,
        "dvc_status": "data_stages_registered",
    }


def train_and_evaluate_models(
    context: dict[str, Any], feature: dict[str, Any]
) -> dict[str, Any]:
    """Train requested models using the successful feature batch."""
    from src.modeling.config import load_modeling_config
    from src.modeling.runner import TrainingRunner

    config = load_modeling_config(
        ROOT / "configs/modeling.yaml",
        overrides={"top_k": context["top_k"]},
    )
    summary = TrainingRunner(config).run(
        algorithm=context["train_algorithm"],
        feature_batch_id=feature["feature_batch_id"],
    )
    mlflow_ids = [
        value.get("mlflow", {}).get("run_id")
        for value in summary["models"].values()
    ]
    mlflow_ids = [value for value in mlflow_ids if value]
    model_paths = [
        value["model_path"] for value in summary["models"].values()
        if value.get("model_path")
    ]
    if not mlflow_ids or not model_paths or not summary.get("report_paths"):
        raise StageExecutionError(
            "Modeling completed without required tracked artifacts."
        )
    return {
        "batch_id": summary["training_batch_id"],
        "feature_batch_id": summary["feature_batch_id"],
        "model_run_id": summary["model_run_id"],
        "status": summary["status"],
        "mlflow_run_ids": mlflow_ids,
        "best_model": summary["comparison"].get("recommended_model"),
        "report_path": summary["report_paths"][0],
        "report_paths": summary["report_paths"],
        "model_paths": model_paths,
        "metrics": {
            name: {
                key: (
                    value
                    if not isinstance(value, float) or math.isfinite(value)
                    else None
                )
                for key, value in result["metrics"].items()
            }
            for name, result in summary["models"].items()
        },
    }


def finalize_model_lineage(
    context: dict[str, Any],
    feature: dict[str, Any],
    modeling: dict[str, Any],
) -> dict[str, Any]:
    """Register model artifacts and complete the end-to-end lineage graph."""
    if not context["run_versioning"]:
        return {"status": "SKIPPED", "reason": "Versioning disabled."}
    from src.versioning.config import load_versioning_config
    from src.versioning.service import VersioningService

    config = load_versioning_config(ROOT / "configs/versioning.yaml")
    service = VersioningService(config)
    for stage in ("models", "model_reports"):
        service.register(stage=stage, batch_id=feature["batch_id"])
    lineage = service.generate_lineage()
    summary = service.generate_summary(lineage)
    verification = service.verify()
    if verification.get("status") != "SUCCESS":
        raise StageExecutionError(
            f"Version verification failed: {verification.get('failures')}"
        )
    return {
        "status": "SUCCESS",
        "model_run_id": modeling["model_run_id"],
        "registry_path": str(config.registry_path),
        "lineage_path": str(config.lineage_path),
        "summary_path": str(config.summary_path),
        "dvc_status": "verified",
        "current_versions": summary["current_dataset_versions"],
    }

def _load_json(path: Path) -> dict[str, Any]:
    import json

    return json.loads(path.read_text(encoding="utf-8"))
