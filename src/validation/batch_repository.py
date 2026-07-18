"""Manifest-first local and S3 raw-batch resolution."""

from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from src.validation.errors import (
    DatasetReadError,
    RawBatchNotFoundError,
    RawManifestNotFoundError,
)
from src.validation.models import RawBatch, RawDatasetAsset

EXPECTED_DATASETS = {
    "users",
    "products",
    "clickstream",
    "purchasehistory",
    "popularity",
}


class RawBatchRepository(Protocol):
    """Resolve one successful raw batch strictly through its manifest."""

    def resolve(self, batch_id: str | None = None) -> RawBatch:
        """Resolve a requested batch or the latest successful batch."""


class LocalRawBatchRepository:
    """Resolve and verify local raw batches."""

    def __init__(self, raw_root: Path) -> None:
        """Initialize the repository at the configured raw root."""
        self._raw_root = raw_root.resolve()

    def resolve(self, batch_id: str | None = None) -> RawBatch:
        """Resolve the manifest and verify all five raw assets."""
        manifest_root = self._raw_root / "manifests"
        if not manifest_root.is_dir():
            raise RawManifestNotFoundError(
                f"Raw manifest directory not found: {manifest_root}"
            )
        candidates: list[tuple[datetime, Path, dict[str, Any]]] = []
        for path in manifest_root.rglob("ingestion_manifest.json"):
            manifest = _read_manifest(path)
            if manifest.get("status") != "SUCCESS":
                continue
            if batch_id is not None and manifest.get("batch_id") != batch_id:
                continue
            candidates.append((_started_at(manifest), path, manifest))
        if not candidates:
            if batch_id is None:
                raise RawBatchNotFoundError(
                    "No successful raw ingestion batch was found."
                )
            raise RawBatchNotFoundError(
                f"Successful raw batch not found: {batch_id}"
            )
        _, manifest_path, manifest = max(candidates, key=lambda item: item[0])
        assets: dict[str, RawDatasetAsset] = {}
        for record in manifest.get("files", []):
            dataset_type = record.get("dataset_type")
            if dataset_type not in EXPECTED_DATASETS:
                continue
            source_path = Path(str(record["destination_path"])).resolve()
            if not source_path.is_file():
                raise DatasetReadError(
                    f"Manifest-resolved raw file is missing: {source_path}"
                )
            checksum = _sha256_file(source_path)
            if checksum != record.get("sha256"):
                raise DatasetReadError(
                    f"Raw checksum differs from manifest for {dataset_type}."
                )
            assets[dataset_type] = RawDatasetAsset(
                dataset_type=dataset_type,
                source_name=str(record["source_name"]),
                source_path=str(source_path),
                local_path=source_path,
                file_type=source_path.suffix.lower().lstrip("."),
                size_bytes=int(record["size_bytes"]),
                sha256=checksum,
                record_count=int(record["record_count"]),
            )
        _require_assets(assets)
        return _build_batch(manifest, str(manifest_path), assets)


class S3RawBatchRepository:
    """Resolve raw manifests and datasets from S3-compatible storage."""

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "raw",
        region: str | None = None,
        endpoint_url: str | None = None,
        profile: str | None = None,
        client: object | None = None,
    ) -> None:
        """Initialize using an injected client or standard AWS chain."""
        if not bucket:
            raise RawBatchNotFoundError("S3 bucket is required.")
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._client = client or _create_s3_client(
            region=region,
            endpoint_url=endpoint_url,
            profile=profile,
        )
        self._temporary = tempfile.TemporaryDirectory(
            prefix="recomart-validation-"
        )

    def resolve(self, batch_id: str | None = None) -> RawBatch:
        """Resolve the latest/requested successful S3 manifest and assets."""
        manifest_prefix = _join_key(self._prefix, "manifests/")
        candidates: list[tuple[datetime, str, dict[str, Any]]] = []
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {
                "Bucket": self._bucket,
                "Prefix": manifest_prefix,
            }
            if token:
                kwargs["ContinuationToken"] = token
            try:
                response = self._client.list_objects_v2(**kwargs)
            except Exception as exc:
                raise RawManifestNotFoundError(
                    "Unable to list S3 ingestion manifests."
                ) from exc
            for item in response.get("Contents", []):
                key = str(item["Key"])
                if not key.endswith("/ingestion_manifest.json"):
                    continue
                manifest = self._read_json_object(key)
                if manifest.get("status") != "SUCCESS":
                    continue
                if batch_id is not None and manifest.get("batch_id") != batch_id:
                    continue
                candidates.append((_started_at(manifest), key, manifest))
            if not response.get("IsTruncated"):
                break
            token = response.get("NextContinuationToken")
        if not candidates:
            raise RawBatchNotFoundError(
                f"Successful S3 raw batch not found: {batch_id or 'latest'}"
            )
        _, manifest_key, manifest = max(candidates, key=lambda item: item[0])
        assets: dict[str, RawDatasetAsset] = {}
        for record in manifest.get("files", []):
            dataset_type = record.get("dataset_type")
            if dataset_type not in EXPECTED_DATASETS:
                continue
            uri = str(record["destination_path"])
            key = _key_from_uri(uri, self._bucket)
            payload = self._read_bytes(key)
            checksum = hashlib.sha256(payload).hexdigest()
            if checksum != record.get("sha256"):
                raise DatasetReadError(
                    f"S3 raw checksum differs for {dataset_type}."
                )
            suffix = Path(str(record["source_name"])).suffix
            local_path = (
                Path(self._temporary.name) / f"{dataset_type}{suffix}"
            )
            local_path.write_bytes(payload)
            assets[dataset_type] = RawDatasetAsset(
                dataset_type=dataset_type,
                source_name=str(record["source_name"]),
                source_path=uri,
                local_path=local_path,
                file_type=suffix.lower().lstrip("."),
                size_bytes=len(payload),
                sha256=checksum,
                record_count=int(record["record_count"]),
            )
        _require_assets(assets)
        manifest_uri = f"s3://{self._bucket}/{manifest_key}"
        return _build_batch(manifest, manifest_uri, assets)

    def _read_json_object(self, key: str) -> dict[str, Any]:
        try:
            payload = self._read_bytes(key)
            decoded = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RawManifestNotFoundError(
                f"Invalid S3 ingestion manifest: {key}"
            ) from exc
        if not isinstance(decoded, dict):
            raise RawManifestNotFoundError(
                f"S3 ingestion manifest is not an object: {key}"
            )
        return decoded

    def _read_bytes(self, key: str) -> bytes:
        try:
            response = self._client.get_object(
                Bucket=self._bucket, Key=key
            )
            return response["Body"].read()
        except Exception as exc:
            raise DatasetReadError(
                f"Unable to read S3 raw object: {key}"
            ) from exc


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RawManifestNotFoundError(
            f"Unreadable ingestion manifest: {path}"
        ) from exc
    if not isinstance(decoded, dict):
        raise RawManifestNotFoundError(
            f"Ingestion manifest must be an object: {path}"
        )
    return decoded


def _build_batch(
    manifest: dict[str, Any],
    manifest_path: str,
    assets: dict[str, RawDatasetAsset],
) -> RawBatch:
    return RawBatch(
        batch_id=str(manifest["batch_id"]),
        ingestion_run_id=str(manifest["run_id"]),
        correlation_id=str(manifest["correlation_id"]),
        started_at=str(manifest["started_at"]),
        manifest_path=manifest_path,
        assets=assets,
    )


def _require_assets(assets: dict[str, RawDatasetAsset]) -> None:
    missing = EXPECTED_DATASETS.difference(assets)
    if missing:
        raise DatasetReadError(
            "Ingestion manifest is missing required datasets: "
            + ", ".join(sorted(missing))
        )


def _started_at(manifest: dict[str, Any]) -> datetime:
    try:
        return datetime.fromisoformat(
            str(manifest["started_at"]).replace("Z", "+00:00")
        )
    except (KeyError, ValueError) as exc:
        raise RawManifestNotFoundError(
            "Ingestion manifest has an invalid started_at value."
        ) from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise DatasetReadError(f"Unable to checksum raw file: {path}") from exc
    return digest.hexdigest()


def _create_s3_client(
    *,
    region: str | None,
    endpoint_url: str | None,
    profile: str | None,
) -> object:
    try:
        import boto3

        return boto3.Session(
            profile_name=profile,
            region_name=region,
        ).client("s3", endpoint_url=endpoint_url)
    except Exception as exc:
        raise RawBatchNotFoundError(
            "Unable to initialize S3 through the standard AWS chain."
        ) from exc


def _key_from_uri(uri: str, expected_bucket: str) -> str:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or parsed.netloc != expected_bucket:
        raise DatasetReadError("Manifest contains an invalid S3 destination URI.")
    return parsed.path.lstrip("/")


def _join_key(prefix: str, suffix: str) -> str:
    return f"{prefix}/{suffix}" if prefix else suffix
