"""Unit and focused integration tests for ingestion and raw storage."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest

from src.ingestion.api_ingestion import PopularityApiIngestionService
from src.ingestion.checksums import sha256_bytes, sha256_file
from src.ingestion.config import (
    IngestionConfig,
    LogConfig,
    RequestConfig,
    S3Config,
    load_ingestion_config,
)
from src.ingestion.errors import (
    ApiIngestionError,
    ConfigurationError,
    SourceFileNotFoundError,
    StorageConflictError,
)
from src.ingestion.file_ingestion import FileIngestionService
from src.ingestion.ingestion_runner import IngestionRunner
from src.ingestion.logging_config import configure_ingestion_logging
from src.ingestion.models import ItemStatus, RunContext
from src.ingestion.storage import LocalStorage, S3Storage

FIXED_TIME = datetime(2026, 7, 19, 1, 2, 3, tzinfo=timezone.utc)
POPULARITY_RECORD = {
    "product_id": 101,
    "average_rating": 4.35,
    "total_ratings": 186,
    "popularity_score": 91.42,
    "trend": "UP",
    "updated_at": "2026-07-19T00:30:00Z",
}


def _request_config(max_attempts: int = 3) -> RequestConfig:
    return RequestConfig(0.1, 0.1, max_attempts, (0.0, 0.0, 0.0))


def _config(root: Path, *, input_path: Path, raw_path: Path) -> IngestionConfig:
    return IngestionConfig(
        project_root=root,
        input_path=input_path,
        required_files=(
            "users.csv",
            "products.json",
            "clickstream.csv",
            "purchasehistory.csv",
        ),
        popularity_api_url="https://popularity.test/api/v1/popularity",
        request=_request_config(),
        storage_type="local",
        local_raw_path=raw_path,
        s3=S3Config("", "raw", None, None, None, 3, (0.0,)),
        logging=LogConfig(
            "INFO", root / "logs", "ingestion.log", 100_000, 2
        ),
    )


def _write_sources(directory: Path) -> None:
    directory.mkdir(parents=True)
    (directory / "users.csv").write_text(
        "user_id,age\n1,24\n2,35\n", encoding="utf-8"
    )
    (directory / "products.json").write_text(
        '[{"product_id": 101}]\n', encoding="utf-8"
    )
    (directory / "clickstream.csv").write_text(
        "event_id,user_id\nabc,1\n", encoding="utf-8"
    )
    (directory / "purchasehistory.csv").write_text(
        "order_id,user_id\nxyz,1\n", encoding="utf-8"
    )


def _api_client(
    handler: Any | None = None,
) -> httpx.Client:
    def success(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[POPULARITY_RECORD], request=request)

    return httpx.Client(transport=httpx.MockTransport(handler or success))


def _context() -> RunContext:
    return RunContext("BATCH_001", "run-1", "correlation-1", FIXED_TIME)


def test_successful_local_ingestion_and_manifest(tmp_path: Path) -> None:
    """One runner call stores all five datasets and the final manifest."""
    incoming = tmp_path / "incoming"
    raw = tmp_path / "raw"
    _write_sources(incoming)
    config = _config(tmp_path, input_path=incoming, raw_path=raw)

    with _api_client() as client:
        result = IngestionRunner(
            config=config,
            storage=LocalStorage(raw),
            api_client=client,
            utc_clock=lambda: FIXED_TIME,
            sleeper=lambda _: None,
        ).run(batch_id="BATCH_001")

    assert result.exit_code == 0
    expected_base = (
        "ingestion_date=2026-07-19/ingestion_hour=01/"
        "batch_id=BATCH_001"
    )
    assert (raw / "file/users" / expected_base / "users.csv").is_file()
    assert (
        raw / "api/popularity" / expected_base / "popularity.json"
    ).is_file()
    manifest_path = (
        raw / "manifests" / expected_base / "ingestion_manifest.json"
    )
    manifest = json.loads(manifest_path.read_text("utf-8"))
    assert manifest["status"] == "SUCCESS"
    assert len(manifest["files"]) == 5
    assert all(record["sha256"] for record in manifest["files"])
    assert (
        next(
            item
            for item in manifest["files"]
            if item["source_type"] == "api"
        )["http_status_code"]
        == 200
    )


def test_file_ingestion_missing_required_file(tmp_path: Path) -> None:
    """Missing required input raises a specific non-retryable error."""
    service = FileIngestionService(
        input_path=tmp_path,
        storage=LocalStorage(tmp_path / "raw"),
        context=_context(),
    )
    with pytest.raises(SourceFileNotFoundError):
        service.ingest("users.csv")


def test_api_timeout_retries_then_succeeds(tmp_path: Path) -> None:
    """A transient timeout is retried and retry metadata is retained."""
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("temporary", request=request)
        return httpx.Response(200, json=[POPULARITY_RECORD], request=request)

    with _api_client(handler) as client:
        record = PopularityApiIngestionService(
            api_url="https://popularity.test/api/v1/popularity",
            request_config=_request_config(),
            storage=LocalStorage(tmp_path / "raw"),
            context=_context(),
            client=client,
            sleeper=sleeps.append,
        ).ingest()

    assert calls == 2
    assert record.retry_count == 1
    assert sleeps == [0.0]
    assert record.status == ItemStatus.SUCCESS.value


def test_api_permanent_failure_is_not_retried(tmp_path: Path) -> None:
    """Permanent client errors fail immediately."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404, request=request)

    with _api_client(handler) as client:
        service = PopularityApiIngestionService(
            api_url="https://popularity.test/api/v1/popularity",
            request_config=_request_config(),
            storage=LocalStorage(tmp_path / "raw"),
            context=_context(),
            client=client,
            sleeper=lambda _: None,
        )
        with pytest.raises(ApiIngestionError) as caught:
            service.ingest()

    assert calls == 1
    assert caught.value.status_code == 404
    assert caught.value.retry_count == 0


def test_local_storage_idempotency_and_conflict(tmp_path: Path) -> None:
    """Same content is reused while different content cannot overwrite raw."""
    storage = LocalStorage(tmp_path / "raw")
    destination = storage.build_destination(
        source_type="file",
        dataset_type="users",
        ingestion_date="2026-07-19",
        ingestion_hour="01",
        batch_id="BATCH_001",
        filename="users.csv",
    )
    first = tmp_path / "first.csv"
    first.write_text("id\n1\n", encoding="utf-8")
    first_checksum = sha256_file(first)

    initial = storage.write_file(
        first, destination, sha256=first_checksum
    )
    repeated = storage.write_file(
        first, destination, sha256=first_checksum
    )
    different = tmp_path / "different.csv"
    different.write_text("id\n2\n", encoding="utf-8")

    assert initial.status is ItemStatus.SUCCESS
    assert repeated.status is ItemStatus.IDEMPOTENT_SUCCESS
    with pytest.raises(StorageConflictError):
        storage.write_file(
            different, destination, sha256=sha256_file(different)
        )
    assert Path(destination.uri).read_bytes() == first.read_bytes()


class _FakeS3Error(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.fail_put_once = False
        self.put_attempts = 0

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        del Bucket
        if Key not in self.objects:
            raise _FakeS3Error("404")
        payload, checksum = self.objects[Key]
        return {
            "Metadata": {"sha256": checksum},
            "ContentLength": len(payload),
        }

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        Metadata: dict[str, str],
        ContentType: str,
    ) -> None:
        del Bucket, ContentType
        self.put_attempts += 1
        if self.fail_put_once and self.put_attempts == 1:
            raise _FakeS3Error("503")
        self.objects[Key] = (Body, Metadata["sha256"])

    def upload_file(
        self,
        filename: str,
        bucket: str,
        key: str,
        ExtraArgs: dict[str, dict[str, str]],
    ) -> None:
        del bucket
        payload = Path(filename).read_bytes()
        self.objects[key] = (
            payload,
            ExtraArgs["Metadata"]["sha256"],
        )


def test_mocked_s3_upload_retry_and_idempotency() -> None:
    """S3-compatible writes retry transient errors and reuse matching objects."""
    client = _FakeS3Client()
    client.fail_put_once = True
    sleeps: list[float] = []
    storage = S3Storage(
        bucket="recomart-test",
        prefix="raw",
        client=client,
        sleeper=sleeps.append,
        max_attempts=3,
        backoff_seconds=(0.0, 0.0),
    )
    destination = storage.build_destination(
        source_type="api",
        dataset_type="popularity",
        ingestion_date="2026-07-19",
        ingestion_hour="01",
        batch_id="BATCH_001",
        filename="popularity.json",
    )
    payload = json.dumps([POPULARITY_RECORD]).encode()
    checksum = sha256_bytes(payload)

    first = storage.write_bytes(payload, destination, sha256=checksum)
    repeated = storage.write_bytes(payload, destination, sha256=checksum)

    assert client.put_attempts == 2
    assert sleeps == [0.0]
    assert first.status is ItemStatus.SUCCESS
    assert repeated.status is ItemStatus.IDEMPOTENT_SUCCESS
    assert destination.uri.startswith("s3://recomart-test/raw/api/")


def test_partial_run_records_failure_and_success_logs(tmp_path: Path) -> None:
    """Controlled missing input produces a partial manifest and audit logs."""
    incoming = tmp_path / "incoming"
    raw = tmp_path / "raw"
    _write_sources(incoming)
    (incoming / "users.csv").unlink()
    config = _config(tmp_path, input_path=incoming, raw_path=raw)
    configure_ingestion_logging(config.logging)

    with _api_client() as client:
        result = IngestionRunner(
            config=config,
            storage=LocalStorage(raw),
            api_client=client,
            utc_clock=lambda: FIXED_TIME,
            sleeper=lambda _: None,
        ).run(batch_id="BATCH_FAILURE")

    log_text = (config.logging.directory / "ingestion.log").read_text("utf-8")
    assert result.exit_code != 0
    assert result.manifest.status == "PARTIAL_SUCCESS"
    assert any(
        error["error_type"] == "SourceFileNotFoundError"
        for error in result.manifest.errors
    )
    assert '"status": "SUCCESS"' in log_text
    assert '"status": "FAILED"' in log_text


def test_credentials_are_redacted_from_logs(tmp_path: Path) -> None:
    """Credential values never reach console or rotating file logs."""
    secret = "super-secret-test-value"
    config = LogConfig("INFO", tmp_path, "ingestion.log", 10_000, 1)
    logger = configure_ingestion_logging(
        config, sensitive_values=(secret,)
    )
    logger.error(
        "A dependency included %s",
        secret,
        extra={"operation": "test", "status": "FAILED"},
    )
    for handler in logger.handlers:
        handler.flush()
    text = (tmp_path / "ingestion.log").read_text("utf-8")
    assert secret not in text
    assert "[REDACTED]" in text


def test_invalid_storage_configuration(tmp_path: Path) -> None:
    """S3 mode without a bucket fails during configuration loading."""
    yaml_path = tmp_path / "ingestion.yaml"
    yaml_path.write_text(
        """
ingestion:
  input_path: incoming
  required_files: [users.csv]
  popularity_api_url: http://localhost/popularity
  request:
    connect_timeout_seconds: 1
    read_timeout_seconds: 1
    max_attempts: 1
    backoff_seconds: [0]
storage:
  type: s3
  local:
    raw_path: raw
  s3:
    bucket: ""
    prefix: raw
    region: ""
    endpoint_url: ""
    profile: ""
    max_attempts: 1
    backoff_seconds: [0]
logging:
  level: INFO
  directory: logs
  filename: ingestion.log
  max_bytes: 1000
  backup_count: 1
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError):
        load_ingestion_config(
            yaml_path,
            project_root=tmp_path,
            environment={},
        )


def test_configuration_precedence(tmp_path: Path) -> None:
    """CLI overrides environment, which overrides YAML."""
    project_config = Path("configs/ingestion.yaml").resolve()
    config = load_ingestion_config(
        project_config,
        project_root=Path.cwd(),
        environment={
            "RECOMART_STORAGE_TYPE": "s3",
            "RECOMART_S3_BUCKET": "environment-bucket",
            "AWS_DEFAULT_REGION": "us-east-1",
        },
        overrides={
            "storage": "local",
            "input_path": str(tmp_path / "incoming"),
        },
    )
    assert config.storage_type == "local"
    assert config.input_path == (tmp_path / "incoming").resolve()
    assert config.s3.bucket == "environment-bucket"
