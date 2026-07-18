"""Typed errors raised by the versioning and lineage subsystem."""


class VersioningError(RuntimeError):
    """Base error for dataset versioning failures."""


class LineageError(VersioningError):
    """Raised when the lineage graph is incomplete or inconsistent."""


class ChecksumError(VersioningError):
    """Raised when an artifact checksum cannot be generated or verified."""


class RegistryError(VersioningError):
    """Raised when the dataset registry cannot be read or written."""


class DVCError(VersioningError):
    """Raised when DVC state or pipeline metadata is invalid."""
