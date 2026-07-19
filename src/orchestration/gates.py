"""Deterministic data-quality and feature-store orchestration gates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.orchestration.contracts import is_success
from src.orchestration.errors import FeatureStoreGateError, QualityGateError


def enforce_quality_gate(
    validation: dict[str, Any], *, strict_quality: bool
) -> dict[str, Any]:
    """Allow technical success and optionally reject any invalid records."""
    status = str(validation.get("status", "FAILED"))
    invalid = int(validation.get("invalid_record_count", 0) or 0)
    if not is_success(status):
        raise QualityGateError(
            f"Validation failed technically: status={status}; "
            f"report={validation.get('report_path')}"
        )
    if strict_quality and (status != "SUCCESS" or invalid > 0):
        raise QualityGateError(
            "Strict quality gate rejected the batch: "
            f"status={status}, invalid_records={invalid}, "
            f"quality_score={validation.get('quality_score')}, "
            f"report={validation.get('report_path')}"
        )
    return {
        "status": "SUCCESS",
        "strict_quality": strict_quality,
        "quality_score": validation.get("quality_score"),
        "invalid_record_count": invalid,
        "report_path": validation.get("report_path"),
    }


def verify_feature_store(feature: dict[str, Any]) -> dict[str, Any]:
    """Verify successful persistence and non-empty modeling feature groups."""
    if not is_success(feature.get("status")):
        raise FeatureStoreGateError(
            f"Feature batch is not successful: {feature.get('status')}"
        )
    counts = feature.get("row_counts", {})
    required = (
        "user_feature_count",
        "item_feature_count",
        "user_item_feature_count",
    )
    empty = [name for name in required if int(counts.get(name, 0)) <= 0]
    if empty:
        raise FeatureStoreGateError(
            f"Required feature tables are empty: {', '.join(empty)}"
        )
    manifest = feature.get("manifest_path")
    if not manifest or not Path(manifest).is_file():
        raise FeatureStoreGateError("Feature manifest is missing.")
    return {
        "status": "SUCCESS",
        "feature_batch_id": feature["feature_batch_id"],
        "database_engine": feature.get("database_engine"),
        "row_counts": counts,
    }
