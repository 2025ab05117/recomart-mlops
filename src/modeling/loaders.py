"""Feature-store and chronological prepared-split loading."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, text

from src.modeling.config import ModelingConfig
from src.modeling.errors import FeatureStoreError


@dataclass(frozen=True)
class TrainingInputs:
    """Feature-store frames, chronological splits, and upstream lineage."""

    feature_batch_id: str
    source_batch_id: str
    preparation_run_id: str
    feature_reference_timestamp: str
    feature_manifest_path: Path
    user_features: pd.DataFrame
    item_features: pd.DataFrame
    user_item_features: pd.DataFrame
    item_similarity_features: pd.DataFrame
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame


def load_training_inputs(
    config: ModelingConfig, feature_batch_id: str | None = None
) -> TrainingInputs:
    """Load the requested/latest successful feature batch and prepared splits."""
    try:
        engine = create_engine(config.database_url, future=True)
        condition = (
            "WHERE feature_batch_id=:batch" if feature_batch_id else
            "WHERE status IN ('SUCCESS','IDEMPOTENT_SUCCESS')"
        )
        ordering = "" if feature_batch_id else "ORDER BY completed_at DESC LIMIT 1"
        with engine.connect() as connection:
            batch = connection.execute(text(
                f"SELECT * FROM feature_batch {condition} {ordering}"
            ), {"batch": feature_batch_id}).mappings().first()
            if not batch:
                raise FeatureStoreError("Feature batch was not found.")
            identifier = batch["feature_batch_id"]
            frames = {
                name: pd.read_sql(text(
                    f"SELECT * FROM {name} WHERE feature_batch_id=:batch"
                ), connection, params={"batch": identifier})
                for name in (
                    "user_features", "item_features", "user_item_features",
                    "item_similarity_features",
                )
            }
    except FeatureStoreError:
        raise
    except Exception as exc:
        raise FeatureStoreError("Unable to load the feature store.") from exc
    manifests = []
    for path in config.feature_path.rglob("feature_manifest.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload["feature_batch_id"] == identifier:
                manifests.append((path, payload))
        except (OSError, KeyError, json.JSONDecodeError):
            continue
    if len(manifests) != 1:
        raise FeatureStoreError("Unique feature manifest could not be resolved.")
    manifest_path, manifest = manifests[0]
    try:
        splits = {
            name: pd.read_parquet(manifest["input_paths"][name])
            for name in ("train", "validation", "test")
        }
    except (OSError, KeyError, ValueError) as exc:
        raise FeatureStoreError("Prepared chronological splits are unavailable.") from exc
    return TrainingInputs(
        feature_batch_id=identifier,
        source_batch_id=batch["source_batch_id"],
        preparation_run_id=batch["preparation_run_id"],
        feature_reference_timestamp=str(batch["feature_reference_timestamp"]),
        feature_manifest_path=manifest_path.resolve(),
        user_features=frames["user_features"],
        item_features=frames["item_features"],
        user_item_features=frames["user_item_features"],
        item_similarity_features=frames["item_similarity_features"],
        train=splits["train"],
        validation=splits["validation"],
        test=splits["test"],
    )
