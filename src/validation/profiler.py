"""Pandas-based dataset profiling and quality-score calculation."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd

from src.validation.config import QualityWeights
from src.validation.models import RuleResult
from src.validation.rules import blank_mask, parse_timestamps
from src.validation.schema import DatasetSchema


def profile_dataset(
    *,
    frame: pd.DataFrame,
    dataset_type: str,
    source_path: str,
    batch_id: str,
    file_type: str,
    file_size: int,
    checksum: str,
    schema: DatasetSchema,
    reference_time: pd.Timestamp,
    future_tolerance_minutes: int,
    valid_count: int,
    invalid_count: int,
    quality_score: float,
) -> dict[str, Any]:
    """Create a complete JSON-safe statistical profile for one dataset."""
    missing_counts = {
        column: int(blank_mask(frame[column]).sum())
        for column in frame.columns
    }
    total = len(frame)
    missing_percentages = {
        column: round(count / total * 100, 4) if total else 0.0
        for column, count in missing_counts.items()
    }
    unique_counts = {
        column: int(frame[column].nunique(dropna=True))
        for column in frame.columns
    }
    duplicate_count = int(frame.duplicated(keep=False).sum())
    numeric_statistics: dict[str, dict[str, Any]] = {}
    for column in schema.numeric_columns:
        if column not in frame.columns:
            continue
        numeric = pd.to_numeric(frame[column], errors="coerce").dropna()
        if numeric.empty:
            numeric_statistics[column] = {"valid_numeric_count": 0}
            continue
        numeric_statistics[column] = {
            "valid_numeric_count": int(len(numeric)),
            "minimum": _number(numeric.min()),
            "maximum": _number(numeric.max()),
            "mean": _number(numeric.mean()),
            "median": _number(numeric.median()),
            "standard_deviation": _number(numeric.std(ddof=1)),
            "percentiles": {
                "p05": _number(numeric.quantile(0.05)),
                "p25": _number(numeric.quantile(0.25)),
                "p50": _number(numeric.quantile(0.50)),
                "p75": _number(numeric.quantile(0.75)),
                "p95": _number(numeric.quantile(0.95)),
            },
        }
    timestamp_statistics: dict[str, dict[str, Any]] = {}
    future_cutoff = reference_time + pd.Timedelta(future_tolerance_minutes, unit="min")
    for column in schema.timestamp_columns:
        if column not in frame.columns:
            continue
        blank = blank_mask(frame[column])
        parsed = parse_timestamps(frame[column])
        valid = parsed.dropna()
        timestamp_statistics[column] = {
            "earliest": _timestamp(valid.min()) if not valid.empty else None,
            "latest": _timestamp(valid.max()) if not valid.empty else None,
            "invalid_timestamp_count": int((parsed.isna() & ~blank).sum()),
            "future_timestamp_count": int((parsed > future_cutoff).sum()),
        }
    categorical_statistics: dict[str, dict[str, Any]] = {}
    excluded = set(schema.numeric_columns) | set(schema.timestamp_columns)
    for column in frame.columns:
        if column in excluded:
            continue
        counts = frame[column].astype("string").value_counts(
            dropna=False
        )
        categorical_statistics[column] = {
            "distinct_value_count": int(frame[column].nunique(dropna=True)),
            "top_values": [
                {"value": str(value), "count": int(count)}
                for value, count in counts.head(5).items()
            ],
        }
    return {
        "dataset_name": dataset_type,
        "source_path": source_path,
        "source_filename": Path(source_path).name,
        "batch_id": batch_id,
        "file_type": file_type,
        "file_size_bytes": file_size,
        "sha256": checksum,
        "total_record_count": total,
        "total_column_count": len(frame.columns),
        "column_names": [str(column) for column in frame.columns],
        "inferred_data_types": {
            column: str(frame[column].dtype) for column in frame.columns
        },
        "expected_data_types": schema.expected_types,
        "missing_value_count": missing_counts,
        "missing_value_percentage": missing_percentages,
        "unique_value_count": unique_counts,
        "duplicate_row_count": duplicate_count,
        "duplicate_percentage": (
            round(duplicate_count / total * 100, 4) if total else 0.0
        ),
        "numeric_statistics": numeric_statistics,
        "categorical_statistics": categorical_statistics,
        "timestamp_statistics": timestamp_statistics,
        "valid_record_count": valid_count,
        "invalid_record_count": invalid_count,
        "overall_dataset_quality_score": quality_score,
    }


def calculate_quality_score(
    *,
    frame: pd.DataFrame,
    schema: DatasetSchema,
    rules: list[RuleResult],
    weights: QualityWeights,
) -> tuple[float, dict[str, float]]:
    """Calculate documented completeness/uniqueness/validity/consistency scores."""
    total = len(frame)
    required_cells = total * len(schema.required_value_columns)
    missing_cells = 0
    for column in schema.required_value_columns:
        missing_cells += (
            total if column not in frame.columns else int(blank_mask(frame[column]).sum())
        )
    completeness = (
        100.0
        if required_cells == 0 and total > 0
        else (
            max(0.0, 100.0 * (1 - missing_cells / required_cells))
            if required_cells
            else 0.0
        )
    )
    uniqueness = _category_score(rules, {"Uniqueness"}, total)
    validity = _category_score(
        rules,
        {"Schema", "Range", "Format", "Business Rules"},
        total,
    )
    consistency = _category_score(
        rules, {"Referential Integrity", "Consistency"}, total
    )
    components = {
        "completeness_score": round(completeness, 2),
        "uniqueness_score": round(uniqueness, 2),
        "validity_score": round(validity, 2),
        "consistency_score": round(consistency, 2),
    }
    overall = (
        completeness * weights.completeness
        + uniqueness * weights.uniqueness
        + validity * weights.validity
        + consistency * weights.consistency
    )
    return round(overall, 2), components


def _category_score(
    rules: list[RuleResult], categories: set[str], total: int
) -> float:
    if total == 0:
        return 0.0
    failed_indices: set[int] = set()
    dataset_failure = False
    for rule in rules:
        if rule.category not in categories or rule.severity != "ERROR":
            continue
        failed_indices.update(rule.failed_indices)
        if rule.failed_record_count and not rule.failed_indices:
            dataset_failure = True
    if dataset_failure:
        return 0.0
    return max(0.0, 100.0 * (1 - len(failed_indices) / total))


def _number(value: Any) -> int | float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    if math.isfinite(number) and number.is_integer():
        return int(number)
    return round(number, 6) if math.isfinite(number) else None


def _timestamp(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).isoformat().replace("+00:00", "Z")


