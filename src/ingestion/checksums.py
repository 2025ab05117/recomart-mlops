"""Streaming checksum and source record-count operations."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from src.ingestion.errors import SourceFileReadError


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Calculate a file SHA-256 checksum without loading it into memory."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(chunk_size):
                digest.update(chunk)
    except OSError as exc:
        raise SourceFileReadError(f"Unable to read source file: {path}") from exc
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    """Calculate a SHA-256 checksum for an in-memory response."""
    return hashlib.sha256(payload).hexdigest()


def count_source_records(path: Path) -> int:
    """Count CSV rows or top-level JSON-array records without mutation."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _count_csv(path)
    if suffix == ".json":
        return _count_json(path)
    raise SourceFileReadError(f"Unsupported raw source format: {path.suffix}")


def _count_csv(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.reader(stream)
            next(reader, None)
            return sum(1 for _ in reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise SourceFileReadError(f"Unable to count CSV records: {path}") from exc


def _count_json(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8") as stream:
            payload: Any = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SourceFileReadError(f"Unable to parse JSON source: {path}") from exc
    if not isinstance(payload, list):
        raise SourceFileReadError(
            f"Expected a top-level JSON array in source: {path}"
        )
    return len(payload)
