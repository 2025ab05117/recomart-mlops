"""Deterministic SHA-256 generation and verification."""

from __future__ import annotations

import hashlib
from pathlib import Path

from src.versioning.errors import ChecksumError


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Return SHA-256 for one readable file."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(chunk_size):
                digest.update(chunk)
    except OSError as exc:
        raise ChecksumError(f"Unable to checksum file: {path}") from exc
    return digest.hexdigest()


def sha256_artifact(path: Path) -> str:
    """Hash a file or directory including relative names and file hashes."""
    if path.is_file():
        return sha256_file(path)
    if not path.is_dir():
        raise ChecksumError(f"Artifact does not exist: {path}")
    digest = hashlib.sha256()
    files = sorted(item for item in path.rglob("*") if item.is_file())
    if not files:
        raise ChecksumError(f"Artifact contains no files: {path}")
    for item in files:
        relative = item.relative_to(path).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(item).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def verify_checksum(path: Path, expected: str) -> bool:
    """Return whether current content matches an expected SHA-256."""
    return sha256_artifact(path) == expected
