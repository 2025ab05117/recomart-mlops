"""Application service coordinating one incoming-to-raw ingestion run."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx

from src.ingestion.api_ingestion import PopularityApiIngestionService
from src.ingestion.config import IngestionConfig
from src.ingestion.errors import ApiIngestionError, IngestionError
from src.ingestion.file_ingestion import FileIngestionService
from src.ingestion.manifest import publish_manifest
from src.ingestion.models import (
    IngestionManifest,
    ItemStatus,
    ManifestFileRecord,
    RunContext,
    RunStatus,
)
from src.ingestion.storage import RawStorage

LOGGER = logging.getLogger(__name__)
UtcClock = Callable[[], datetime]
SleepFunction = Callable[[float], None]


@dataclass(frozen=True)
class IngestionRunResult:
    """Completed run manifest and its committed destination."""

    manifest: IngestionManifest
    manifest_path: str

    @property
    def exit_code(self) -> int:
        """Return zero only for a fully successful run."""
        return 0 if self.manifest.status == RunStatus.SUCCESS.value else 2


class IngestionRunner:
    """Coordinate file and REST sources through one storage abstraction."""

    def __init__(
        self,
        *,
        config: IngestionConfig,
        storage: RawStorage,
        api_client: httpx.Client | None = None,
        utc_clock: UtcClock | None = None,
        sleeper: SleepFunction = time.sleep,
    ) -> None:
        """Initialize the runner with injected infrastructure dependencies."""
        self._config = config
        self._storage = storage
        self._api_client = api_client
        self._utc_clock = utc_clock or (
            lambda: datetime.now(timezone.utc)
        )
        self._sleeper = sleeper

    def run(self, *, batch_id: str | None = None) -> IngestionRunResult:
        """Attempt all configured sources, publish a manifest, and exit.

        Successful metadata is retained even if a later source fails. The final
        manifest is always attempted after all source operations.
        """
        started_at = self._utc_clock().astimezone(timezone.utc)
        effective_batch_id = batch_id or _generate_batch_id(started_at)
        _validate_batch_id(effective_batch_id)
        context = RunContext(
            batch_id=effective_batch_id,
            run_id=str(uuid.uuid4()),
            correlation_id=str(uuid.uuid4()),
            started_at=started_at,
        )
        LOGGER.info(
            "Ingestion started",
            extra=_context_fields(context, "run_ingestion", "STARTED"),
        )
        records: list[ManifestFileRecord] = []
        errors: list[dict[str, str]] = []
        file_service = FileIngestionService(
            input_path=self._config.input_path,
            storage=self._storage,
            context=context,
        )
        for source_name in self._config.required_files:
            try:
                records.append(file_service.ingest(source_name))
            except IngestionError as exc:
                record = _failure_record(
                    source_type="file",
                    dataset_type=Path(source_name).stem,
                    source_name=source_name,
                    exc=exc,
                )
                records.append(record)
                errors.append(_error_entry(record))
                LOGGER.error(
                    "File ingestion failed",
                    extra={
                        **_context_fields(
                            context, "ingest_file", "FAILED"
                        ),
                        "source_type": "file",
                        "dataset_type": Path(source_name).stem,
                    },
                    exc_info=exc,
                )

        api_service = PopularityApiIngestionService(
            api_url=self._config.popularity_api_url,
            request_config=self._config.request,
            storage=self._storage,
            context=context,
            client=self._api_client,
            sleeper=self._sleeper,
        )
        try:
            records.append(api_service.ingest())
        except IngestionError as exc:
            record = _failure_record(
                source_type="api",
                dataset_type="popularity",
                source_name="popularity_api",
                exc=exc,
                request_url=self._config.popularity_api_url,
            )
            records.append(record)
            errors.append(_error_entry(record))
            LOGGER.error(
                "Popularity API ingestion failed",
                extra={
                    **_context_fields(context, "ingest_api", "FAILED"),
                    "source_type": "api",
                    "dataset_type": "popularity",
                },
                exc_info=exc,
            )

        completed_at = self._utc_clock().astimezone(timezone.utc)
        run_status = _aggregate_status(records)
        manifest = IngestionManifest(
            batch_id=context.batch_id,
            run_id=context.run_id,
            correlation_id=context.correlation_id,
            started_at=_format_utc(started_at),
            completed_at=_format_utc(completed_at),
            status=run_status.value,
            storage_type=self._config.storage_type,
            source_path=_relative_path_label(
                self._config.input_path, self._config.project_root
            ),
            destination=self._config.destination_label,
            files=records,
            errors=errors,
        )
        manifest_destination = self._storage.build_destination(
            source_type="manifests",
            dataset_type=None,
            ingestion_date=context.ingestion_date,
            ingestion_hour=context.ingestion_hour,
            batch_id=context.batch_id,
            filename="ingestion_manifest.json",
        )
        if self._storage.exists(manifest_destination):
            if run_status is not RunStatus.SUCCESS:
                raise IngestionError(
                    "A finalized manifest already exists for this failed rerun."
                )
            manifest_path = manifest_destination.uri
            manifest_status = ItemStatus.IDEMPOTENT_SUCCESS.value
        else:
            manifest_result = publish_manifest(
                manifest, storage=self._storage, context=context
            )
            manifest_path = manifest_result.destination_path
            manifest_status = manifest_result.status.value
        LOGGER.log(
            logging.INFO if run_status is RunStatus.SUCCESS else logging.ERROR,
            "Ingestion completed",
            extra={
                **_context_fields(
                    context, "run_ingestion", run_status.value
                ),
                "dataset_type": "manifest",
                "source_type": "manifest",
                "manifest_status": manifest_status,
                "duration_ms": round(
                    (completed_at - started_at).total_seconds() * 1000, 2
                ),
            },
        )
        return IngestionRunResult(manifest, manifest_path)


def _failure_record(
    *,
    source_type: str,
    dataset_type: str,
    source_name: str,
    exc: IngestionError,
    request_url: str | None = None,
) -> ManifestFileRecord:
    return ManifestFileRecord(
        source_type=source_type,
        dataset_type=dataset_type,
        source_name=source_name,
        status=ItemStatus.FAILED.value,
        error_type=type(exc).__name__,
        error_message=str(exc),
        http_status_code=(
            exc.status_code if isinstance(exc, ApiIngestionError) else None
        ),
        request_url=request_url,
        retry_count=(
            exc.retry_count if isinstance(exc, ApiIngestionError) else None
        ),
    )


def _error_entry(record: ManifestFileRecord) -> dict[str, str]:
    return {
        "source_type": record.source_type,
        "dataset_type": record.dataset_type,
        "error_type": record.error_type or "IngestionError",
        "message": record.error_message or "Ingestion failed.",
    }


def _aggregate_status(records: list[ManifestFileRecord]) -> RunStatus:
    succeeded = sum(
        record.status
        in {ItemStatus.SUCCESS.value, ItemStatus.IDEMPOTENT_SUCCESS.value}
        for record in records
    )
    if succeeded == len(records):
        return RunStatus.SUCCESS
    if succeeded:
        return RunStatus.PARTIAL_SUCCESS
    return RunStatus.FAILED


def _generate_batch_id(now: datetime) -> str:
    suffix = uuid.uuid4().hex[:6]
    return f"RECO_{now.strftime('%Y%m%d_%H%M%S')}_{suffix}"


def _validate_batch_id(batch_id: str) -> None:
    if (
        not batch_id
        or len(batch_id) > 100
        or any(
            not (character.isalnum() or character in {"-", "_"})
            for character in batch_id
        )
    ):
        raise IngestionError(
            "batch_id may contain only letters, numbers, hyphens, and underscores."
        )


def _context_fields(
    context: RunContext, operation: str, status: str
) -> dict[str, object]:
    return {
        "batch_id": context.batch_id,
        "run_id": context.run_id,
        "correlation_id": context.correlation_id,
        "operation": operation,
        "status": status,
    }


def _format_utc(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _relative_path_label(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)

