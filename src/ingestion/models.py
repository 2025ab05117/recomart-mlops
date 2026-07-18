"""Typed value objects shared across ingestion services."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class ItemStatus(StrEnum):
    """Outcome of one source ingestion attempt."""

    SUCCESS = "SUCCESS"
    IDEMPOTENT_SUCCESS = "IDEMPOTENT_SUCCESS"
    FAILED = "FAILED"


class RunStatus(StrEnum):
    """Aggregate outcome of one ingestion run."""

    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"


@dataclass(frozen=True)
class StorageDestination:
    """Logical relative path and provider-specific destination URI."""

    relative_path: str
    uri: str


@dataclass(frozen=True)
class StorageWriteResult:
    """Verified result of a storage write."""

    destination_path: str
    status: ItemStatus
    size_bytes: int
    sha256: str


@dataclass
class ManifestFileRecord:
    """Metadata for a file or API dataset attempted during ingestion."""

    source_type: str
    dataset_type: str
    source_name: str
    destination_path: str | None = None
    record_count: int | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    status: str = ItemStatus.FAILED.value
    error_type: str | None = None
    error_message: str | None = None
    http_status_code: int | None = None
    request_url: str | None = None
    retry_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe record excluding fields that do not apply."""
        return {
            key: value
            for key, value in asdict(self).items()
            if value is not None
        }


@dataclass
class IngestionManifest:
    """Complete audit record for one ingestion run."""

    batch_id: str
    run_id: str
    correlation_id: str
    started_at: str
    completed_at: str
    status: str
    storage_type: str
    source_path: str
    destination: str
    files: list[ManifestFileRecord] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    manifest_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical JSON representation of the manifest."""
        return {
            "manifest_version": self.manifest_version,
            "batch_id": self.batch_id,
            "run_id": self.run_id,
            "correlation_id": self.correlation_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status,
            "storage_type": self.storage_type,
            "source_path": self.source_path,
            "destination": self.destination,
            "files": [record.to_dict() for record in self.files],
            "errors": self.errors,
        }


@dataclass(frozen=True)
class RunContext:
    """Stable identifiers and UTC partition values for an ingestion run."""

    batch_id: str
    run_id: str
    correlation_id: str
    started_at: datetime

    @property
    def ingestion_date(self) -> str:
        """Return the UTC ingestion-date partition."""
        return self.started_at.astimezone(timezone.utc).date().isoformat()

    @property
    def ingestion_hour(self) -> str:
        """Return the zero-padded UTC ingestion-hour partition."""
        return self.started_at.astimezone(timezone.utc).strftime("%H")
