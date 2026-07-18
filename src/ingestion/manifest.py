"""Ingestion manifest construction and immutable publication."""

from __future__ import annotations

import json

from src.ingestion.checksums import sha256_bytes
from src.ingestion.models import (
    IngestionManifest,
    RunContext,
    StorageWriteResult,
)
from src.ingestion.storage import RawStorage


def serialize_manifest(manifest: IngestionManifest) -> bytes:
    """Serialize a manifest deterministically as formatted UTF-8 JSON."""
    return (
        json.dumps(
            manifest.to_dict(),
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def publish_manifest(
    manifest: IngestionManifest,
    *,
    storage: RawStorage,
    context: RunContext,
) -> StorageWriteResult:
    """Publish the final manifest after all source attempts are recorded."""
    payload = serialize_manifest(manifest)
    destination = storage.build_destination(
        source_type="manifests",
        dataset_type=None,
        ingestion_date=context.ingestion_date,
        ingestion_hour=context.ingestion_hour,
        batch_id=context.batch_id,
        filename="ingestion_manifest.json",
    )
    return storage.write_bytes(
        payload, destination, sha256=sha256_bytes(payload)
    )
