"""Coordinate one manifest-driven profiling and validation execution."""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

from src.validation.batch_repository import RawBatchRepository
from src.validation.config import ValidationConfig
from src.validation.errors import (
    DatasetReadError,
    ValidationConflictError,
    ValidationError,
)
from src.validation.models import (
    DatasetValidationResult,
    RawBatch,
    ValidationManifest,
    ValidationRunStatus,
)
from src.validation.output_writer import (
    ValidationOutputWriter,
    find_existing_validation_manifest,
)
from src.validation.reporting import (
    build_quality_summary,
    generate_pdf_report,
)
from src.validation.validators import DatasetValidator, read_raw_dataset

LOGGER = logging.getLogger(__name__)
DATASET_ORDER = (
    "users",
    "products",
    "clickstream",
    "purchasehistory",
    "popularity",
)
UtcClock = Callable[[], datetime]


@dataclass(frozen=True)
class ValidationRunResult:
    """Final validation manifest and process outcome."""

    manifest: ValidationManifest

    def exit_code(self, *, strict_quality: bool) -> int:
        """Map technical/quality outcomes to documented process codes."""
        if self.manifest.status == ValidationRunStatus.FAILED.value:
            return 2
        if (
            strict_quality
            and self.manifest.status
            == ValidationRunStatus.COMPLETED_WITH_QUALITY_ISSUES.value
        ):
            return 1
        return 0


class ValidationRunner:
    """Resolve, validate, split, profile, report, and manifest one raw batch."""

    def __init__(
        self,
        *,
        config: ValidationConfig,
        repository: RawBatchRepository,
        utc_clock: UtcClock | None = None,
    ) -> None:
        """Initialize the application service with injected dependencies."""
        self._config = config
        self._repository = repository
        self._utc_clock = utc_clock or (
            lambda: datetime.now(timezone.utc)
        )

    def run(self, *, batch_id: str | None = None) -> ValidationRunResult:
        """Perform one validation run and publish immutable artifacts."""
        execution_started = time.perf_counter()
        started_at = self._utc_clock().astimezone(timezone.utc)
        batch = self._repository.resolve(batch_id)
        source_checksums = {
            name: asset.sha256 for name, asset in batch.assets.items()
        }
        existing = self._resolve_existing(batch, source_checksums)
        if existing is not None:
            LOGGER.info(
                "Validation outputs already exist and match inputs",
                extra={
                    "batch_id": batch.batch_id,
                    "validation_run_id": existing.validation_run_id,
                    "correlation_id": existing.correlation_id,
                    "operation": "validate_batch",
                    "status": "IDEMPOTENT_SUCCESS",
                    "duration_ms": round(
                        (time.perf_counter() - execution_started) * 1000, 2
                    ),
                },
            )
            return ValidationRunResult(existing)

        validation_run_id = str(uuid.uuid4())
        correlation_id = batch.correlation_id
        context = {
            "batch_id": batch.batch_id,
            "validation_run_id": validation_run_id,
            "correlation_id": correlation_id,
        }
        LOGGER.info(
            "Validation started",
            extra={
                **context,
                "operation": "validate_batch",
                "status": "STARTED",
            },
        )
        frames: dict[str, pd.DataFrame] = {}
        technical_errors: list[dict[str, str]] = []
        for dataset_type in DATASET_ORDER:
            asset = batch.assets[dataset_type]
            load_started = time.perf_counter()
            try:
                frames[dataset_type] = read_raw_dataset(asset)
                LOGGER.info(
                    "Dataset loaded",
                    extra={
                        **context,
                        "dataset_type": dataset_type,
                        "operation": "load_dataset",
                        "status": "SUCCESS",
                        "records_checked": len(frames[dataset_type]),
                        "duration_ms": round(
                            (time.perf_counter() - load_started) * 1000, 2
                        ),
                    },
                )
            except DatasetReadError as exc:
                frames[dataset_type] = pd.DataFrame()
                technical_errors.append(
                    {
                        "dataset_type": dataset_type,
                        "error_type": type(exc).__name__,
                        "message": str(exc),
                    }
                )
                LOGGER.error(
                    "Dataset read failed",
                    extra={
                        **context,
                        "dataset_type": dataset_type,
                        "operation": "load_dataset",
                        "status": "FAILED",
                    },
                    exc_info=exc,
                )
                if self._config.fail_fast:
                    raise

        validator = DatasetValidator(self._config)
        results: list[DatasetValidationResult] = []
        references: dict[str, pd.DataFrame] = {}
        for dataset_type in DATASET_ORDER:
            validation_started = time.perf_counter()
            result = validator.validate(
                dataset_type=dataset_type,
                frame=frames[dataset_type],
                asset=batch.assets[dataset_type],
                reference_frames=references,
                batch_id=batch.batch_id,
                validation_run_id=validation_run_id,
                validation_time=started_at,
            )
            results.append(result)
            references[dataset_type] = frames[dataset_type]
            if result.critical_schema_failure:
                technical_errors.append(
                    {
                        "dataset_type": dataset_type,
                        "error_type": "SchemaValidationError",
                        "message": (
                            "Dataset is empty or required columns are missing."
                        ),
                    }
                )
            LOGGER.info(
                "Dataset profiling and validation completed",
                extra={
                    **context,
                    "dataset_type": dataset_type,
                    "operation": "validate_dataset",
                    "status": (
                        "SUCCESS"
                        if result.invalid_records == 0
                        else "QUALITY_ISSUES"
                    ),
                    "records_checked": result.total_records,
                    "failed_record_count": result.invalid_records,
                    "duration_ms": round(
                        (time.perf_counter() - validation_started) * 1000, 2
                    ),
                },
            )
            for rule in result.rules:
                if rule.status in {"FAILED", "WARNING"}:
                    LOGGER.warning(
                        "Validation rule reported an issue",
                        extra={
                            **context,
                            "dataset_type": dataset_type,
                            "rule_id": rule.rule_id,
                            "operation": "apply_rule",
                            "status": rule.status,
                            "records_checked": rule.records_checked,
                            "failed_record_count": rule.failed_record_count,
                        },
                    )

        writer = ValidationOutputWriter(
            config=self._config,
            batch_id=batch.batch_id,
            validation_time=started_at,
        )
        for result in results:
            writer.write_dataset(result)
            LOGGER.info(
                "Validated and quarantine datasets written",
                extra={
                    **context,
                    "dataset_type": result.dataset_type,
                    "operation": "write_validation_outputs",
                    "status": "SUCCESS",
                    "records_checked": result.total_records,
                    "failed_record_count": result.invalid_records,
                },
            )

        status = _run_status(results, technical_errors)
        overall_score = _overall_quality_score(results)
        completed_at = self._utc_clock().astimezone(timezone.utc)
        summary = build_quality_summary(
            batch_id=batch.batch_id,
            validation_run_id=validation_run_id,
            correlation_id=correlation_id,
            started_at=_format_utc(started_at),
            completed_at=_format_utc(completed_at),
            status=status.value,
            raw_manifest_path=batch.manifest_path,
            overall_quality_score=overall_score,
            results=results,
            config=self._config,
            technical_errors=technical_errors,
        )
        report_path = writer.paths.report_directory / "data_quality_report.pdf"
        summary_path = (
            writer.paths.report_directory / "data_quality_summary.json"
        )
        summary["artifacts"] = {
            "pdf_report": str(report_path),
            "json_summary": str(summary_path),
        }
        pdf_payload = generate_pdf_report(summary=summary, results=results)
        writer.write_bytes(report_path, pdf_payload)
        writer.write_json("data_quality_summary.json", summary)
        LOGGER.info(
            "Data-quality report generated",
            extra={
                **context,
                "operation": "generate_report",
                "status": "SUCCESS",
            },
        )

        dataset_manifest_records = [
            {
                "dataset_type": result.dataset_type,
                "source_path": result.source_path,
                "source_sha256": result.source_sha256,
                "validated_path": result.validated_path,
                "quarantine_path": result.quarantine_path,
                "validation_errors_path": result.validation_errors_path,
                "total_records": result.total_records,
                "valid_records": result.valid_records,
                "invalid_records": result.invalid_records,
                "quality_score": result.quality_score,
                "rules_passed": sum(
                    rule.status == "PASSED" for rule in result.rules
                ),
                "rules_failed": sum(
                    rule.status == "FAILED" for rule in result.rules
                ),
                "warnings": sum(
                    rule.status == "WARNING" for rule in result.rules
                ),
                "rules_skipped": sum(
                    rule.status == "SKIPPED" for rule in result.rules
                ),
            }
            for result in results
        ]
        manifest = ValidationManifest(
            batch_id=batch.batch_id,
            validation_run_id=validation_run_id,
            correlation_id=correlation_id,
            started_at=_format_utc(started_at),
            completed_at=_format_utc(completed_at),
            status=status.value,
            raw_manifest_path=batch.manifest_path,
            raw_ingestion_run_id=batch.ingestion_run_id,
            configuration_version=self._config.config_version,
            configuration_sha256=self._config.config_sha256,
            source_checksums=source_checksums,
            datasets=dataset_manifest_records,
            overall_quality_score=overall_score,
            report_path=str(report_path),
            summary_path=str(summary_path),
            errors=technical_errors,
        )
        writer.write_json("validation_manifest.json", manifest.to_dict())
        LOGGER.log(
            logging.ERROR
            if status is ValidationRunStatus.FAILED
            else logging.INFO,
            "Validation completed",
            extra={
                **context,
                "operation": "validate_batch",
                "status": status.value,
                "records_checked": sum(
                    result.total_records for result in results
                ),
                "failed_record_count": sum(
                    result.invalid_records for result in results
                ),
                "duration_ms": round(
                    (time.perf_counter() - execution_started) * 1000, 2
                ),
            },
        )
        return ValidationRunResult(manifest)

    def _resolve_existing(
        self,
        batch: RawBatch,
        source_checksums: dict[str, str],
    ) -> ValidationManifest | None:
        path = find_existing_validation_manifest(
            self._config.report_path, batch.batch_id
        )
        if path is None:
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            existing = ValidationManifest(**payload)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
            raise ValidationConflictError(
                f"Existing validation manifest is unreadable: {path}"
            ) from exc
        if (
            existing.configuration_sha256 != self._config.config_sha256
            or existing.source_checksums != source_checksums
        ):
            raise ValidationConflictError(
                "Existing batch validation uses different source checksums "
                "or configuration. Use a new immutable validation version."
            )
        if not Path(existing.report_path).is_file() or not Path(
            existing.summary_path
        ).is_file():
            raise ValidationConflictError(
                "Existing validation manifest references missing reports."
            )
        existing.idempotent = True
        return existing


def _run_status(
    results: list[DatasetValidationResult],
    technical_errors: list[dict[str, str]],
) -> ValidationRunStatus:
    if technical_errors:
        return ValidationRunStatus.FAILED
    if any(
        result.invalid_records
        or any(rule.status == "FAILED" for rule in result.rules)
        for result in results
    ):
        return ValidationRunStatus.COMPLETED_WITH_QUALITY_ISSUES
    return ValidationRunStatus.SUCCESS


def _overall_quality_score(
    results: list[DatasetValidationResult],
) -> float:
    total_records = sum(result.total_records for result in results)
    if total_records:
        return round(
            sum(
                result.quality_score * result.total_records
                for result in results
            )
            / total_records,
            2,
        )
    if not results:
        return 0.0
    return round(
        sum(result.quality_score for result in results) / len(results), 2
    )


def _format_utc(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


