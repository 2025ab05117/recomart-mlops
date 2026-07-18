"""Structured rule, profile, dataset, and run validation models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import pandas as pd


class RuleStatus(StrEnum):
    """Supported validation rule outcomes."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    WARNING = "WARNING"
    SKIPPED = "SKIPPED"


class Severity(StrEnum):
    """Supported validation rule severities."""

    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class ValidationRunStatus(StrEnum):
    """Aggregate validation execution states."""

    SUCCESS = "SUCCESS"
    COMPLETED_WITH_QUALITY_ISSUES = "COMPLETED_WITH_QUALITY_ISSUES"
    FAILED = "FAILED"


@dataclass
class RuleResult:
    """One structured validation rule outcome."""

    rule_id: str
    rule_name: str
    dataset_type: str
    column_name: str | None
    category: str
    severity: str
    status: str
    records_checked: int
    failed_record_count: int
    failure_percentage: float
    message: str
    sample_failed_values: list[Any] = field(default_factory=list)
    failed_indices: list[int] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict[str, Any]:
        """Return the machine-readable rule result without internal indices."""
        payload = asdict(self)
        payload.pop("failed_indices", None)
        return payload


@dataclass(frozen=True)
class RawDatasetAsset:
    """One manifest-resolved raw dataset and its source metadata."""

    dataset_type: str
    source_name: str
    source_path: str
    local_path: Path
    file_type: str
    size_bytes: int
    sha256: str
    record_count: int


@dataclass(frozen=True)
class RawBatch:
    """Latest or explicitly selected successful raw ingestion batch."""

    batch_id: str
    ingestion_run_id: str
    correlation_id: str
    started_at: str
    manifest_path: str
    assets: dict[str, RawDatasetAsset]


@dataclass
class DatasetValidationResult:
    """Profile, rules, row split, and destinations for one dataset."""

    dataset_type: str
    source_path: str
    source_sha256: str
    file_type: str
    frame: pd.DataFrame
    valid_frame: pd.DataFrame
    invalid_frame: pd.DataFrame
    rules: list[RuleResult]
    profile: dict[str, Any]
    quality_score: float
    component_scores: dict[str, float]
    critical_schema_failure: bool = False
    validated_path: str | None = None
    quarantine_path: str | None = None
    validation_errors_path: str | None = None

    @property
    def total_records(self) -> int:
        """Return source record count."""
        return len(self.frame)

    @property
    def valid_records(self) -> int:
        """Return records passing every ERROR-level row rule."""
        return len(self.valid_frame)

    @property
    def invalid_records(self) -> int:
        """Return quarantined record count."""
        return len(self.invalid_frame)

    def to_summary_dict(self) -> dict[str, Any]:
        """Return complete JSON-safe profile and validation details."""
        return {
            "dataset_type": self.dataset_type,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "file_type": self.file_type,
            "total_records": self.total_records,
            "valid_records": self.valid_records,
            "invalid_records": self.invalid_records,
            "quality_score": self.quality_score,
            "component_scores": self.component_scores,
            "critical_schema_failure": self.critical_schema_failure,
            "validated_path": self.validated_path,
            "quarantine_path": self.quarantine_path,
            "validation_errors_path": self.validation_errors_path,
            "profile": self.profile,
            "rules": [rule.to_dict() for rule in self.rules],
        }


@dataclass
class ValidationManifest:
    """Traceability and outcome manifest for one validation execution."""

    batch_id: str
    validation_run_id: str
    correlation_id: str
    started_at: str
    completed_at: str
    status: str
    raw_manifest_path: str
    raw_ingestion_run_id: str
    configuration_version: str
    configuration_sha256: str
    source_checksums: dict[str, str]
    datasets: list[dict[str, Any]]
    overall_quality_score: float
    report_path: str
    summary_path: str
    errors: list[dict[str, str]]
    idempotent: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical validation-manifest representation."""
        return asdict(self)
