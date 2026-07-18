"""Enterprise-style multi-model training, evaluation, tracking, and reporting."""

from __future__ import annotations

import json
import logging
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from src.modeling.collaborative import FunkSVDRecommender
from src.modeling.config import ModelingConfig
from src.modeling.content_based import ContentBasedRecommender
from src.modeling.evaluation import ranking_metrics, rating_metrics
from src.modeling.loaders import TrainingInputs, load_training_inputs
from src.modeling.persistence import save_model_bundle
from src.modeling.reporting import write_reports
from src.modeling.tracking import configure_mlflow, log_experiment

LOGGER = logging.getLogger(__name__)


class TrainingRunner:
    """Train selected algorithms against immutable feature-store lineage."""

    def __init__(self, config: ModelingConfig) -> None:
        """Initialize with reproducible configuration."""
        self.config = config

    def run(
        self, *, algorithm: str = "all",
        feature_batch_id: str | None = None,
    ) -> dict[str, Any]:
        """Train, evaluate, persist, track, compare, and report models."""
        started = datetime.now(timezone.utc)
        model_run_id = f"MODEL_{started.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        inputs = load_training_inputs(self.config, feature_batch_id)
        context = {
            "model_run_id": model_run_id,
            "feature_batch_id": inputs.feature_batch_id,
        }
        LOGGER.info("Training started", extra={
            **context, "operation": "training_run", "status": "STARTED"
        })
        configure_mlflow(self.config)
        results: dict[str, Any] = {}
        if algorithm in {"all", "collaborative"}:
            results["collaborative"] = self._collaborative(
                inputs, model_run_id, context
            )
        if algorithm in {"all", "content"}:
            results["content_based"] = self._content(
                inputs, model_run_id, context
            )
        comparison = compare_models(results, self.config.top_k)
        completed = datetime.now(timezone.utc)
        summary = {
            "model_run_id": model_run_id,
            "training_batch_id": inputs.source_batch_id,
            "feature_batch_id": inputs.feature_batch_id,
            "preparation_run_id": inputs.preparation_run_id,
            "started_at": _utc(started),
            "completed_at": _utc(completed),
            "status": "SUCCESS",
            "git_commit": _git_commit(self.config.root),
            "configuration_hash": self.config.sha256,
            "dataset": {
                name: {
                    "rows": len(getattr(inputs, name)),
                    "explicit_ratings": int(
                        getattr(inputs, name).explicit_rating.notna().sum()
                    ),
                }
                for name in ("train", "validation", "test")
            },
            "models": results,
            "comparison": comparison,
        }
        report_dir = self.config.report_path / f"model_run_id={model_run_id}"
        report_paths = write_reports(
            report_dir, summary=summary, comparison=comparison
        )
        summary["report_paths"] = [str(path) for path in report_paths]
        LOGGER.info("Training completed", extra={
            **context, "operation": "training_run", "status": "SUCCESS",
            "duration_ms": round(
                (completed - started).total_seconds() * 1000, 2
            ),
        })
        return summary

    def _collaborative(
        self, inputs: TrainingInputs, model_run_id: str,
        context: dict[str, str],
    ) -> dict[str, Any]:
        timer = time.perf_counter()
        model = FunkSVDRecommender(
            factors=self.config.factors,
            learning_rate=self.config.learning_rate,
            regularization=self.config.regularization,
            epochs=self.config.epochs,
            random_seed=self.config.random_seed,
        ).fit(inputs.train)
        training_time = time.perf_counter() - timer
        metrics = {
            **rating_metrics(model.predict, inputs.test),
            **ranking_metrics(
                lambda user, k: model.recommend(user, k),
                inputs.test, inputs.train, top_k=self.config.top_k,
                threshold=self.config.threshold,
                catalog=set(inputs.item_features.product_id),
                similarity=inputs.item_similarity_features,
            ),
            "training_time_seconds": training_time,
        }
        example_user = int(inputs.test.user_id.iloc[0])
        recommendations = model.recommend(example_user, self.config.top_k)
        model_dir = (
            self.config.model_path / "collaborative"
            / f"model_run_id={model_run_id}"
        )
        parameters = {
            "algorithm": "FunkSVD", "factors": self.config.factors,
            "learning_rate": self.config.learning_rate,
            "regularization": self.config.regularization,
            "epochs": self.config.epochs,
            "random_seed": self.config.random_seed,
        }
        metadata = self._metadata(
            inputs, model_run_id, "collaborative", "FunkSVD",
            metrics, training_time,
        )
        artifacts = save_model_bundle(
            model, model_dir, metadata=metadata,
            configuration=self.config.snapshot,
        )
        evaluation = model_dir / "evaluation.json"
        evaluation.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        artifacts.append(evaluation)
        tracking = log_experiment(
            self.config, run_name=f"{model_run_id}-collaborative",
            parameters={**parameters, "feature_batch_id": inputs.feature_batch_id,
                        "train_rows": len(inputs.train)},
            metrics=metrics, artifacts=artifacts,
            tags={"model_run_id": model_run_id, "model_type": "collaborative",
                  "source_batch_id": inputs.source_batch_id},
        )
        LOGGER.info("Collaborative training finished", extra={
            **context, "model_name": "FunkSVD", "operation": "train_model",
            "status": "SUCCESS", "duration_ms": training_time * 1000,
        })
        return {
            "model_name": "collaborative", "algorithm": "FunkSVD",
            "parameters": parameters, "metrics": metrics,
            "model_path": str(artifacts[0]), "metadata_path": str(artifacts[1]),
            "mlflow": tracking, "example_user_id": example_user,
            "recommendation_example": recommendations.to_dict("records"),
            "memory_usage_bytes": artifacts[0].stat().st_size,
        }

    def _content(
        self, inputs: TrainingInputs, model_run_id: str,
        context: dict[str, str],
    ) -> dict[str, Any]:
        timer = time.perf_counter()
        model = ContentBasedRecommender(
            top_k=self.config.content_top_k
        ).fit(inputs.item_features)
        training_time = time.perf_counter() - timer
        metrics = ranking_metrics(
            lambda user, k: model.recommend_for_user(
                inputs.train, user, k
            ),
            inputs.test, inputs.train, top_k=self.config.top_k,
            threshold=self.config.threshold,
            catalog=set(inputs.item_features.product_id),
            similarity=inputs.item_similarity_features,
        )
        metrics.update({
            "rmse": float("nan"), "mae": float("nan"),
            "training_time_seconds": training_time,
            "similarity_quality": float(
                inputs.item_similarity_features.combined_similarity_score.mean()
            ),
        })
        example_product = int(inputs.item_features.product_id.iloc[0])
        recommendations = model.similar_items(
            example_product, self.config.top_k
        )
        model_dir = (
            self.config.model_path / "content_based"
            / f"model_run_id={model_run_id}"
        )
        parameters = {
            "algorithm": "cosine_content",
            "top_k": self.config.content_top_k,
            "features": "category,brand,price,average_rating",
        }
        metadata = self._metadata(
            inputs, model_run_id, "content_based", "cosine_content",
            metrics, training_time,
        )
        metadata["feature_importance"] = model.feature_importance
        artifacts = save_model_bundle(
            model, model_dir, metadata=metadata,
            configuration=self.config.snapshot,
        )
        evaluation = model_dir / "evaluation.json"
        evaluation.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        artifacts.append(evaluation)
        tracking = log_experiment(
            self.config, run_name=f"{model_run_id}-content",
            parameters={**parameters, "feature_batch_id": inputs.feature_batch_id,
                        "catalog_size": len(inputs.item_features)},
            metrics=metrics, artifacts=artifacts,
            tags={"model_run_id": model_run_id, "model_type": "content_based",
                  "source_batch_id": inputs.source_batch_id},
        )
        LOGGER.info("Content training finished", extra={
            **context, "model_name": "cosine_content",
            "operation": "train_model", "status": "SUCCESS",
            "duration_ms": training_time * 1000,
        })
        return {
            "model_name": "content_based", "algorithm": "cosine_content",
            "parameters": parameters, "metrics": metrics,
            "model_path": str(artifacts[0]), "metadata_path": str(artifacts[1]),
            "mlflow": tracking, "example_product_id": example_product,
            "recommendation_example": recommendations.to_dict("records"),
            "feature_importance": model.feature_importance,
            "memory_usage_bytes": artifacts[0].stat().st_size,
        }

    def _metadata(
        self, inputs: TrainingInputs, model_run_id: str,
        model_name: str, algorithm: str, metrics: dict[str, float],
        duration: float,
    ) -> dict[str, Any]:
        return {
            "model_run_id": model_run_id,
            "training_batch_id": inputs.source_batch_id,
            "feature_batch_id": inputs.feature_batch_id,
            "model_name": model_name, "algorithm": algorithm,
            "status": "SUCCESS", "git_commit": _git_commit(self.config.root),
            "configuration_hash": self.config.sha256,
            "feature_reference_timestamp": inputs.feature_reference_timestamp,
            "training_duration_seconds": duration, "metrics": metrics,
        }


def compare_models(
    results: dict[str, Any], top_k: int
) -> dict[str, Any]:
    """Compare common ranking/operational metrics and recommend a winner."""
    if len(results) == 1:
        winner = next(iter(results))
    else:
        score = {}
        for name, result in results.items():
            metrics = result["metrics"]
            score[name] = (
                metrics.get(f"precision_at_{top_k}", 0)
                + metrics.get(f"recall_at_{top_k}", 0)
                + metrics.get(f"ndcg_at_{top_k}", 0)
                + metrics.get("coverage", 0)
            )
        winner = max(score, key=score.get)
    metrics_to_show = [
        "rmse", f"precision_at_{top_k}", f"recall_at_{top_k}",
        f"map_at_{top_k}", f"ndcg_at_{top_k}", "coverage",
        "training_time_seconds", "inference_time_seconds",
    ]
    table = [["Metric", *results.keys()]]
    for metric in metrics_to_show:
        table.append([
            metric,
            *[results[name]["metrics"].get(metric) for name in results],
        ])
    return {
        "recommended_model": winner,
        "recommendation_reason": (
            f"{winner} achieved the strongest combined precision, recall, "
            "NDCG, and catalog coverage score for this chronological test set."
        ),
        "comparison_table": table,
    }


def _git_commit(root: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
