"""Immutable local and S3-compatible raw-storage implementations."""

from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path, PurePosixPath
from typing import Callable, Protocol

from src.ingestion.checksums import sha256_bytes, sha256_file
from src.ingestion.errors import StorageConflictError, StorageWriteError
from src.ingestion.models import (
    ItemStatus,
    StorageDestination,
    StorageWriteResult,
)

LOGGER = logging.getLogger(__name__)
SleepFunction = Callable[[float], None]


class RawStorage(Protocol):
    """Provider-neutral immutable raw-storage contract."""

    @property
    def destination_label(self) -> str:
        """Return a safe manifest destination description."""

    def build_destination(
        self,
        *,
        source_type: str,
        dataset_type: str | None,
        ingestion_date: str,
        ingestion_hour: str,
        batch_id: str,
        filename: str,
    ) -> StorageDestination:
        """Build a destination using the canonical partition layout."""

    def exists(self, destination: StorageDestination) -> bool:
        """Return whether a destination object exists."""

    def write_file(
        self,
        source_path: Path,
        destination: StorageDestination,
        *,
        sha256: str,
    ) -> StorageWriteResult:
        """Write or idempotently reuse a source file."""

    def write_bytes(
        self,
        payload: bytes,
        destination: StorageDestination,
        *,
        sha256: str,
    ) -> StorageWriteResult:
        """Write or idempotently reuse an in-memory payload."""


class LocalStorage:
    """Immutable local-filesystem raw storage."""

    def __init__(self, root: Path) -> None:
        """Initialize storage rooted at the configured raw directory."""
        self._root = root.resolve()

    @property
    def destination_label(self) -> str:
        """Return the local raw root used by manifest records."""
        return str(self._root)

    def build_destination(
        self,
        *,
        source_type: str,
        dataset_type: str | None,
        ingestion_date: str,
        ingestion_hour: str,
        batch_id: str,
        filename: str,
    ) -> StorageDestination:
        """Build and validate a canonical local partition destination."""
        relative = _logical_path(
            source_type=source_type,
            dataset_type=dataset_type,
            ingestion_date=ingestion_date,
            ingestion_hour=ingestion_hour,
            batch_id=batch_id,
            filename=filename,
        )
        path = (self._root / Path(relative)).resolve()
        if not path.is_relative_to(self._root):
            raise StorageWriteError("Destination escapes the local raw root.")
        return StorageDestination(relative, str(path))

    def exists(self, destination: StorageDestination) -> bool:
        """Return whether the local destination exists."""
        return Path(destination.uri).is_file()

    def write_file(
        self,
        source_path: Path,
        destination: StorageDestination,
        *,
        sha256: str,
    ) -> StorageWriteResult:
        """Copy a source file atomically without changing source bytes."""
        target = Path(destination.uri)
        if target.exists():
            return self._existing_result(target, sha256)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
            shutil.copyfile(source_path, temporary)
            actual_checksum = sha256_file(temporary)
            if actual_checksum != sha256:
                temporary.unlink(missing_ok=True)
                raise StorageWriteError(
                    f"Checksum verification failed for {destination.relative_path}"
                )
            try:
                os.link(temporary, target)
                temporary.unlink()
            except FileExistsError:
                temporary.unlink(missing_ok=True)
                return self._existing_result(target, sha256)
            return StorageWriteResult(
                destination.uri,
                ItemStatus.SUCCESS,
                target.stat().st_size,
                sha256,
            )
        except StorageWriteError:
            raise
        except OSError as exc:
            raise StorageWriteError(
                f"Unable to write local destination: {destination.relative_path}"
            ) from exc

    def write_bytes(
        self,
        payload: bytes,
        destination: StorageDestination,
        *,
        sha256: str,
    ) -> StorageWriteResult:
        """Atomically write bytes and enforce checksum-based immutability."""
        target = Path(destination.uri)
        if target.exists():
            return self._existing_result(target, sha256)
        if sha256_bytes(payload) != sha256:
            raise StorageWriteError("Provided payload checksum is inconsistent.")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
            temporary.write_bytes(payload)
            try:
                os.link(temporary, target)
                temporary.unlink()
            except FileExistsError:
                temporary.unlink(missing_ok=True)
                return self._existing_result(target, sha256)
            return StorageWriteResult(
                destination.uri,
                ItemStatus.SUCCESS,
                len(payload),
                sha256,
            )
        except OSError as exc:
            raise StorageWriteError(
                f"Unable to write local destination: {destination.relative_path}"
            ) from exc

    @staticmethod
    def _existing_result(
        target: Path, expected_checksum: str
    ) -> StorageWriteResult:
        actual_checksum = sha256_file(target)
        if actual_checksum != expected_checksum:
            raise StorageConflictError(
                f"Immutable destination conflict: {target}"
            )
        return StorageWriteResult(
            str(target),
            ItemStatus.IDEMPOTENT_SUCCESS,
            target.stat().st_size,
            actual_checksum,
        )


class S3Storage:
    """Immutable AWS S3 or S3-compatible raw storage."""

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "raw",
        region: str | None = None,
        endpoint_url: str | None = None,
        profile: str | None = None,
        max_attempts: int = 3,
        backoff_seconds: tuple[float, ...] = (1, 2, 4),
        client: object | None = None,
        sleeper: SleepFunction = time.sleep,
    ) -> None:
        """Initialize S3 storage using the standard AWS credential chain."""
        if not bucket:
            raise StorageWriteError("S3 bucket must not be empty.")
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._max_attempts = max_attempts
        self._backoffs = backoff_seconds
        self._sleeper = sleeper
        self._client = client or _create_s3_client(
            region=region,
            endpoint_url=endpoint_url,
            profile=profile,
        )

    @property
    def destination_label(self) -> str:
        """Return the S3 bucket and configured raw prefix."""
        suffix = f"/{self._prefix}" if self._prefix else ""
        return f"s3://{self._bucket}{suffix}"

    def build_destination(
        self,
        *,
        source_type: str,
        dataset_type: str | None,
        ingestion_date: str,
        ingestion_hour: str,
        batch_id: str,
        filename: str,
    ) -> StorageDestination:
        """Build a canonical S3 object key."""
        relative = _logical_path(
            source_type=source_type,
            dataset_type=dataset_type,
            ingestion_date=ingestion_date,
            ingestion_hour=ingestion_hour,
            batch_id=batch_id,
            filename=filename,
        )
        key = f"{self._prefix}/{relative}" if self._prefix else relative
        return StorageDestination(relative, f"s3://{self._bucket}/{key}")

    def exists(self, destination: StorageDestination) -> bool:
        """Return whether an S3 object exists."""
        key = self._key(destination)
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except Exception as exc:
            if _s3_error_code(exc) in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise _translate_s3_error(exc, key) from exc

    def write_file(
        self,
        source_path: Path,
        destination: StorageDestination,
        *,
        sha256: str,
    ) -> StorageWriteResult:
        """Upload a source file with retries and immutable checksum metadata."""
        existing = self._existing_result(destination, sha256)
        if existing is not None:
            return existing
        key = self._key(destination)

        def upload() -> None:
            self._client.upload_file(
                str(source_path),
                self._bucket,
                key,
                ExtraArgs={"Metadata": {"sha256": sha256}},
            )

        self._retry(upload, key)
        return StorageWriteResult(
            destination.uri,
            ItemStatus.SUCCESS,
            source_path.stat().st_size,
            sha256,
        )

    def write_bytes(
        self,
        payload: bytes,
        destination: StorageDestination,
        *,
        sha256: str,
    ) -> StorageWriteResult:
        """Upload response bytes with retries and immutable checksum metadata."""
        if sha256_bytes(payload) != sha256:
            raise StorageWriteError("Provided payload checksum is inconsistent.")
        existing = self._existing_result(destination, sha256)
        if existing is not None:
            return existing
        key = self._key(destination)

        def upload() -> None:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=payload,
                Metadata={"sha256": sha256},
                ContentType="application/json",
            )

        self._retry(upload, key)
        return StorageWriteResult(
            destination.uri, ItemStatus.SUCCESS, len(payload), sha256
        )

    def _existing_result(
        self,
        destination: StorageDestination,
        expected_checksum: str,
    ) -> StorageWriteResult | None:
        key = self._key(destination)
        try:
            response = self._client.head_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            if _s3_error_code(exc) in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise _translate_s3_error(exc, key) from exc
        metadata = response.get("Metadata", {})
        actual_checksum = metadata.get("sha256")
        if actual_checksum != expected_checksum:
            raise StorageConflictError(
                f"Immutable S3 destination conflict: {destination.uri}"
            )
        return StorageWriteResult(
            destination.uri,
            ItemStatus.IDEMPOTENT_SUCCESS,
            int(response.get("ContentLength", 0)),
            expected_checksum,
        )

    def _retry(self, operation: Callable[[], None], key: str) -> None:
        for attempt in range(1, self._max_attempts + 1):
            try:
                operation()
                return
            except Exception as exc:
                if not _is_transient_s3_error(exc) or attempt >= self._max_attempts:
                    raise _translate_s3_error(exc, key) from exc
                delay = _backoff(self._backoffs, attempt)
                LOGGER.warning(
                    "S3 upload retry scheduled",
                    extra={
                        "operation": "s3_upload",
                        "status": "RETRY",
                        "retry_attempt": attempt,
                    },
                )
                self._sleeper(delay)

    def _key(self, destination: StorageDestination) -> str:
        return (
            f"{self._prefix}/{destination.relative_path}"
            if self._prefix
            else destination.relative_path
        )


def _logical_path(
    *,
    source_type: str,
    dataset_type: str | None,
    ingestion_date: str,
    ingestion_hour: str,
    batch_id: str,
    filename: str,
) -> str:
    safe_source = _safe_component(source_type, "source type")
    safe_batch = _safe_component(batch_id, "batch ID")
    safe_filename = _safe_component(filename, "filename")
    parts = [safe_source]
    if dataset_type is not None:
        parts.append(_safe_component(dataset_type, "dataset type"))
    parts.extend(
        [
            f"ingestion_date={_safe_component(ingestion_date, 'date')}",
            f"ingestion_hour={_safe_component(ingestion_hour, 'hour')}",
            f"batch_id={safe_batch}",
            safe_filename,
        ]
    )
    return PurePosixPath(*parts).as_posix()


def _safe_component(value: str, label: str) -> str:
    normalized = str(value).strip()
    if (
        not normalized
        or normalized in {".", ".."}
        or "/" in normalized
        or "\\" in normalized
    ):
        raise StorageWriteError(f"Unsafe {label} in storage destination.")
    return normalized


def _create_s3_client(
    *,
    region: str | None,
    endpoint_url: str | None,
    profile: str | None,
) -> object:
    try:
        import boto3

        session = boto3.Session(
            profile_name=profile,
            region_name=region,
        )
        return session.client("s3", endpoint_url=endpoint_url)
    except Exception as exc:
        raise StorageWriteError(
            "Unable to initialize S3 client from the AWS credential chain."
        ) from exc


def _s3_error_code(exc: Exception) -> str | None:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return None
    error = response.get("Error", {})
    return str(error.get("Code")) if error.get("Code") is not None else None


def _is_transient_s3_error(exc: Exception) -> bool:
    code = _s3_error_code(exc)
    if code in {
        "408",
        "429",
        "500",
        "502",
        "503",
        "504",
        "RequestTimeout",
        "SlowDown",
        "InternalError",
        "ServiceUnavailable",
    }:
        return True
    return exc.__class__.__name__ in {
        "ConnectionClosedError",
        "ConnectTimeoutError",
        "EndpointConnectionError",
        "ReadTimeoutError",
    }


def _translate_s3_error(exc: Exception, key: str) -> StorageWriteError:
    code = _s3_error_code(exc)
    if code in {"NoSuchBucket", "404"}:
        return StorageWriteError(
            f"S3 destination bucket or object was not found for key: {key}"
        )
    if code in {
        "AccessDenied",
        "InvalidAccessKeyId",
        "SignatureDoesNotMatch",
        "ExpiredToken",
        "403",
    }:
        return StorageWriteError(
            f"S3 authentication or authorization failed for key: {key}"
        )
    return StorageWriteError(f"S3 operation failed for key: {key}")


def _backoff(backoffs: tuple[float, ...], attempt: int) -> float:
    if not backoffs:
        return 0.0
    return backoffs[min(attempt - 1, len(backoffs) - 1)]

