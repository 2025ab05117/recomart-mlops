"""Incoming file verification and immutable raw publication."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Callable

from src.ingestion.checksums import count_source_records, sha256_file
from src.ingestion.errors import (
    SourceFileNotFoundError,
    SourceFileReadError,
)
from src.ingestion.models import ManifestFileRecord, RunContext
from src.ingestion.storage import RawStorage

LOGGER = logging.getLogger(__name__)
Clock = Callable[[], float]


class FileIngestionService:
    """Verify and publish required incoming files without transformation."""

    def __init__(
        self,
        *,
        input_path: Path,
        storage: RawStorage,
        context: RunContext,
        clock: Clock = time.perf_counter,
    ) -> None:
        """Initialize file ingestion dependencies."""
        self._input_path = input_path.resolve()
        self._storage = storage
        self._context = context
        self._clock = clock

    def ingest(self, source_name: str) -> ManifestFileRecord:
        """Verify, count, checksum, and publish one required source file.

        Args:
            source_name: Safe basename configured as required input.

        Returns:
            Successful manifest metadata for the source.

        Raises:
            SourceFileNotFoundError: If the required file is absent.
            SourceFileReadError: If it is unreadable or malformed.
            StorageWriteError: If immutable publication fails.
        """
        started = self._clock()
        source_path = (self._input_path / source_name).resolve()
        if source_path.parent != self._input_path:
            raise SourceFileReadError(f"Unsafe source file name: {source_name}")
        if not source_path.is_file():
            LOGGER.error(
                "Required source file missing",
                extra=self._log_fields(
                    source_name, "verify_source", "FAILED", started
                ),
            )
            raise SourceFileNotFoundError(
                f"Required source file not found: {source_path}"
            )
        if not os.access(source_path, os.R_OK):
            raise SourceFileReadError(
                f"Required source file is not readable: {source_path}"
            )

        dataset_type = source_path.stem
        checksum = sha256_file(source_path)
        record_count = count_source_records(source_path)
        LOGGER.info(
            "Source file verified",
            extra=self._log_fields(
                dataset_type, "verify_source", "SUCCESS", started
            ),
        )
        destination = self._storage.build_destination(
            source_type="file",
            dataset_type=dataset_type,
            ingestion_date=self._context.ingestion_date,
            ingestion_hour=self._context.ingestion_hour,
            batch_id=self._context.batch_id,
            filename=source_name,
        )
        result = self._storage.write_file(
            source_path, destination, sha256=checksum
        )
        LOGGER.info(
            "Source file stored",
            extra=self._log_fields(
                dataset_type, "write_raw_file", result.status.value, started
            ),
        )
        return ManifestFileRecord(
            source_type="file",
            dataset_type=dataset_type,
            source_name=source_name,
            destination_path=result.destination_path,
            record_count=record_count,
            size_bytes=result.size_bytes,
            sha256=result.sha256,
            status=result.status.value,
        )

    def _log_fields(
        self,
        dataset_type: str,
        operation: str,
        status: str,
        started: float,
    ) -> dict[str, object]:
        return {
            "batch_id": self._context.batch_id,
            "run_id": self._context.run_id,
            "correlation_id": self._context.correlation_id,
            "source_type": "file",
            "dataset_type": Path(dataset_type).stem,
            "operation": operation,
            "status": status,
            "duration_ms": round((self._clock() - started) * 1000, 2),
        }
