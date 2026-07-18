"""Feature definition and lineage record generation."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pandas as pd

from src.feature_engineering.features import FeatureFrames


def build_definitions(
    frames: FeatureFrames, version: str, generated_at: str
) -> pd.DataFrame:
    """Build a lightweight registry entry for every materialized feature."""
    rows: list[dict[str, Any]] = []
    groups = {
        "user": ("user", frames.users),
        "item": ("item", frames.items),
        "user_item": ("user_item", frames.user_items),
        "cooccurrence": ("item_pair", frames.cooccurrence),
        "similarity": ("directed_item_pair", frames.similarity),
    }
    excluded = {
        "feature_batch_id", "source_batch_id",
        "feature_reference_timestamp", "created_at",
    }
    for group, (entity, frame) in groups.items():
        for column in frame.columns:
            if column in excluded:
                continue
            rows.append({
                "feature_name": column,
                "feature_group": group,
                "entity_type": entity,
                "data_type": str(frame[column].dtype),
                "description": _description(column),
                "calculation_logic": _logic(column),
                "source_columns": json.dumps(_sources(column)),
                "default_value": "0" if column.endswith("_count") else None,
                "null_handling": _null_handling(column),
                "feature_version": version,
                "owner": "recomart-mlops",
                "is_active": True,
                "created_at": generated_at,
                "updated_at": generated_at,
            })
    return pd.DataFrame(rows).drop_duplicates(
        ["feature_name", "feature_version"]
    )


def build_lineage(
    definitions: pd.DataFrame,
    frames: FeatureFrames,
    *,
    feature_batch_id: str,
    source_checksums: dict[str, str],
    transformation_version: str,
    generated_at: str,
) -> pd.DataFrame:
    """Create feature-level lineage tied to prepared checksums."""
    table_by_group = {
        "user": "user_features",
        "item": "item_features",
        "user_item": "user_item_features",
        "cooccurrence": "item_cooccurrence_features",
        "similarity": "item_similarity_features",
    }
    rows = []
    checksum = next(iter(source_checksums.values()))
    for record in definitions.to_dict(orient="records"):
        rows.append({
            "lineage_id": str(uuid.uuid4()),
            "feature_batch_id": feature_batch_id,
            "feature_name": record["feature_name"],
            "source_dataset": "prepared/" + frames.metadata["source_split"],
            "source_columns": record["source_columns"],
            "transformation_name": record["calculation_logic"],
            "transformation_version": transformation_version,
            "transformation_parameters": json.dumps(frames.metadata),
            "source_checksum": checksum,
            "output_table": table_by_group[record["feature_group"]],
            "generated_at": generated_at,
        })
    return pd.DataFrame(rows)


def _description(name: str) -> str:
    return name.replace("_", " ").capitalize() + " recommendation feature."


def _logic(name: str) -> str:
    if "ratio" in name or "rate" in name:
        return "safe_ratio"
    if "similarity" in name:
        return "configured_similarity"
    if name.endswith("_count") or name.startswith("total_"):
        return "leakage_safe_group_aggregation"
    if "days_since" in name:
        return "feature_reference_timestamp_minus_latest_event"
    return "deterministic_prepared_data_transformation"


def _sources(name: str) -> list[str]:
    if "rating" in name:
        return ["explicit_rating"]
    if "price" in name:
        return ["products_prepared.price"]
    if "category" in name:
        return ["products_prepared.category", "interaction_weight"]
    if "brand" in name:
        return ["products_prepared.brand", "interaction_weight"]
    return ["train.interaction_type", "train.event_timestamp"]


def _null_handling(name: str) -> str:
    if "rating" in name:
        return "Null when no explicit rating exists; never replaced with zero."
    if "ratio" in name or "rate" in name:
        return "Null when denominator is zero."
    if "days_since_last_purchase" in name:
        return "Null when no purchase exists."
    return "Counts and spend default to zero; unsupported metrics remain null."
