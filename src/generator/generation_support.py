"""Shared deterministic and publication support for generator modules."""

from __future__ import annotations

import hashlib
import json
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.generator.errors import OutputPublicationError

UUID_NAMESPACE = uuid.UUID("3f8a1c28-6816-5f06-bbf2-e3f51963ee0e")


def create_random(seed: int, domain: str) -> random.Random:
    """Create an independently reproducible random generator."""
    digest = hashlib.sha256(f"{seed}:{domain}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], byteorder="big"))


def deterministic_uuid(seed: int, domain: str, identity: str) -> str:
    """Return a stable UUID for a seeded domain object."""
    return str(uuid.uuid5(UUID_NAMESPACE, f"{seed}:{domain}:{identity}"))


def format_utc_timestamp(value: datetime) -> str:
    """Format a timezone-aware datetime as ISO 8601 UTC."""
    if value.tzinfo is None:
        raise ValueError("Timestamp must be timezone-aware.")
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def write_csv(
    frame: pd.DataFrame, output_path: Path, *, overwrite: bool
) -> None:
    """Atomically publish a DataFrame as UTF-8 CSV."""
    _prepare(output_path, overwrite)
    temporary = output_path.with_suffix(f"{output_path.suffix}.tmp")
    try:
        frame.to_csv(temporary, index=False, encoding="utf-8")
        temporary.replace(output_path)
    except (OSError, ValueError) as exc:
        temporary.unlink(missing_ok=True)
        raise OutputPublicationError(
            f"Unable to publish CSV: {output_path}"
        ) from exc


def write_json_array(
    records: list[dict[str, Any]],
    output_path: Path,
    *,
    overwrite: bool,
) -> None:
    """Atomically publish records as a UTF-8 JSON array."""
    _prepare(output_path, overwrite)
    temporary = output_path.with_suffix(f"{output_path.suffix}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(
                records,
                stream,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            stream.write("\n")
        temporary.replace(output_path)
    except (OSError, TypeError, ValueError) as exc:
        temporary.unlink(missing_ok=True)
        raise OutputPublicationError(
            f"Unable to publish JSON: {output_path}"
        ) from exc


def _prepare(output_path: Path, overwrite: bool) -> None:
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OutputPublicationError(
            f"Unable to create output directory: {output_path.parent}"
        ) from exc
    if output_path.exists() and not overwrite:
        raise OutputPublicationError(
            f"Output already exists and is immutable: {output_path}"
        )
