"""Typed errors for profiling and validation execution."""


class ValidationError(Exception):
    """Base exception for validation failures."""


class RawBatchNotFoundError(ValidationError):
    """Raised when the requested or latest successful raw batch is absent."""


class RawManifestNotFoundError(ValidationError):
    """Raised when no usable ingestion manifest can be resolved."""


class DatasetReadError(ValidationError):
    """Raised when a manifest-resolved raw dataset cannot be parsed."""


class SchemaValidationError(ValidationError):
    """Raised for a critical schema condition that prevents safe validation."""


class ReportGenerationError(ValidationError):
    """Raised when JSON or PDF reporting cannot be completed."""


class ValidationConfigurationError(ValidationError):
    """Raised when validation configuration is missing or inconsistent."""


class ValidationStorageWriteError(ValidationError):
    """Raised when validated, quarantine, or report output cannot be written."""


class ValidationConflictError(ValidationStorageWriteError):
    """Raised when immutable validation output has incompatible content."""
