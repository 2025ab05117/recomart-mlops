"""Domain-specific errors for incoming-to-raw ingestion."""


class IngestionError(Exception):
    """Base exception for ingestion failures."""


class ConfigurationError(IngestionError):
    """Raised when ingestion configuration is missing or inconsistent."""


class SourceFileNotFoundError(IngestionError):
    """Raised when a required incoming source file does not exist."""


class SourceFileReadError(IngestionError):
    """Raised when an incoming source file cannot be read or counted."""


class ApiIngestionError(IngestionError):
    """Raised when REST popularity ingestion cannot produce valid data."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_count: int = 0,
    ) -> None:
        """Initialize an API failure with safe response metadata."""
        super().__init__(message)
        self.status_code = status_code
        self.retry_count = retry_count


class StorageWriteError(IngestionError):
    """Raised when raw data cannot be written or verified."""


class StorageConflictError(StorageWriteError):
    """Raised when an immutable destination has different content."""
