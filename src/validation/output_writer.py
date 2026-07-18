"""Immutable validated, quarantine, summary, and manifest output publication."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.validation.config import ValidationConfig
from src.validation.errors import (
    ValidationConflictError,
    ValidationStorageWriteError,
)
from src.validation.models import DatasetValidationResult


@dataclass(frozen=True)
class ValidationOutputPaths:
    """All partitioned destinations for one validation run."""

    validated_directories: dict[str, Path]
    quarantine_directories: dict[str, Path]
    report_directory: Path


class ValidationOutputWriter:
    """Publish immutable validation outputs while preserving source formats."""

    def __init__(
        self,
        *,
        config: ValidationConfig,
        batch_id: str,
        validation_time: datetime,
    ) -> None:
        """Build consistent UTC partitions for one batch."""
        utc = validation_time.astimezone(timezone.utc)
        self._config = config
        self._batch_id = batch_id
        date_partition = f"validation_date={utc.date().isoformat()}"
        hour_partition = f"validation_hour={utc.strftime('%H')}"
        batch_partition = f"batch_id={batch_id}"
        self.paths = ValidationOutputPaths(
            validated_directories={
                dataset: config.validated_path
                / dataset
                / date_partition
                / hour_partition
                / batch_partition
                for dataset in config.required_columns
            },
            quarantine_directories={
                dataset: config.quarantine_path
                / dataset
                / date_partition
                / hour_partition
                / batch_partition
                for dataset in config.required_columns
            },
            report_directory=config.report_path
            / date_partition
            / hour_partition
            / batch_partition,
        )

    def write_dataset(self, result: DatasetValidationResult) -> None:
        """Write valid, invalid, and rule diagnostic artifacts."""
        dataset = result.dataset_type
        suffix = ".csv" if result.file_type == "csv" else ".json"
        validated_path = (
            self.paths.validated_directories[dataset] / f"{dataset}{suffix}"
        )
        invalid_path = (
            self.paths.quarantine_directories[dataset]
            / f"invalid_{dataset}{suffix}"
        )
        errors_path = (
            self.paths.quarantine_directories[dataset]
            / "validation_errors.json"
        )
        if suffix == ".csv":
            valid_payload = _csv_bytes(result.valid_frame)
            invalid_payload = _csv_bytes(
                _csv_quarantine_frame(result.invalid_frame)
            )
        else:
            valid_payload = _json_frame_bytes(result.valid_frame)
            invalid_payload = _json_frame_bytes(result.invalid_frame)
        self.write_bytes(validated_path, valid_payload)
        self.write_bytes(invalid_path, invalid_payload)
        error_payload = _json_bytes(
            {
                "batch_id": self._batch_id,
                "dataset_type": dataset,
                "invalid_record_count": result.invalid_records,
                "rule_results": [
                    rule.to_dict()
                    for rule in result.rules
                    if rule.status != "PASSED"
                ],
            }
        )
        self.write_bytes(errors_path, error_payload)
        result.validated_path = str(validated_path)
        result.quarantine_path = str(invalid_path)
        result.validation_errors_path = str(errors_path)

    def write_json(self, filename: str, payload: dict[str, Any]) -> str:
        """Write a report-directory JSON artifact immutably."""
        path = self.paths.report_directory / filename
        self.write_bytes(path, _json_bytes(payload))
        return str(path)

    def write_bytes(self, path: Path, payload: bytes) -> str:
        """Atomically create or idempotently verify an immutable artifact."""
        checksum = hashlib.sha256(payload).hexdigest()
        if path.exists():
            existing = hashlib.sha256(path.read_bytes()).hexdigest()
            if existing != checksum:
                raise ValidationConflictError(
                    f"Immutable validation output conflict: {path}"
                )
            return str(path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
            temporary.write_bytes(payload)
            try:
                os.link(temporary, path)
                temporary.unlink()
            except FileExistsError:
                temporary.unlink(missing_ok=True)
                existing = hashlib.sha256(path.read_bytes()).hexdigest()
                if existing != checksum:
                    raise ValidationConflictError(
                        f"Immutable validation output conflict: {path}"
                    )
            return str(path)
        except ValidationConflictError:
            raise
        except OSError as exc:
            raise ValidationStorageWriteError(
                f"Unable to publish validation output: {path}"
            ) from exc


def find_existing_validation_manifest(
    report_root: Path, batch_id: str
) -> Path | None:
    """Find a previously finalized validation manifest for a batch."""
    if not report_root.is_dir():
        return None
    matches = list(
        report_root.glob(
            f"validation_date=*/validation_hour=*/"
            f"batch_id={batch_id}/validation_manifest.json"
        )
    )
    return max(matches, key=lambda path: path.stat().st_mtime) if matches else None


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False, lineterminator="\n").encode("utf-8")


def _csv_quarantine_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in ("validation_error_codes", "validation_error_messages"):
        if column in result.columns:
            result[column] = result[column].map(
                lambda value: " | ".join(value)
                if isinstance(value, list)
                else value
            )
    return result


def _json_frame_bytes(frame: pd.DataFrame) -> bytes:
    records = frame.astype(object).where(pd.notna(frame), None).to_dict(
        orient="records"
    )
    return _json_bytes(records)


def _json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
            default=str,
        )
        + "\n"
    ).encode("utf-8")
