"""Structured console and rotating-file logging for ingestion."""

from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from src.ingestion.config import LogConfig
from src.ingestion.errors import ConfigurationError

LOG_FIELDS = (
    "batch_id",
    "run_id",
    "correlation_id",
    "source_type",
    "dataset_type",
    "operation",
    "status",
    "retry_attempt",
    "duration_ms",
)


class JsonLogFormatter(logging.Formatter):
    """Render stable ingestion log fields as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        """Format one record without exposing unrelated process state."""
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "log_level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }
        for field_name in LOG_FIELDS:
            value = getattr(record, field_name, None)
            if value is not None:
                payload[field_name] = value
        if record.exc_info:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False)


class SecretRedactionFilter(logging.Filter):
    """Redact configured credential values from messages and arguments."""

    def __init__(self, sensitive_values: Iterable[str] = ()) -> None:
        """Store non-empty values that must never appear in emitted logs."""
        super().__init__()
        self._values = tuple(
            value for value in sensitive_values if isinstance(value, str) and value
        )

    def filter(self, record: logging.LogRecord) -> bool:
        """Replace sensitive values before formatters receive the record."""
        message = record.getMessage()
        for value in self._values:
            message = message.replace(value, "[REDACTED]")
        record.msg = message
        record.args = ()
        return True


def configure_ingestion_logging(
    config: LogConfig,
    *,
    sensitive_values: Iterable[str] = (),
) -> logging.Logger:
    """Configure console and rotating file handlers for the ingestion namespace.

    Args:
        config: Validated log settings.
        sensitive_values: Credential values to redact defensively.

    Returns:
        The configured ``src.ingestion`` logger.

    Raises:
        ConfigurationError: If the log directory or file cannot be created.
    """
    try:
        config.directory.mkdir(parents=True, exist_ok=True)
        log_path = config.directory / config.filename
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=config.max_bytes,
            backupCount=config.backup_count,
            encoding="utf-8",
        )
    except OSError as exc:
        raise ConfigurationError(
            f"Unable to initialize ingestion log directory: {config.directory}"
        ) from exc

    formatter = JsonLogFormatter()
    redactor = SecretRedactionFilter(sensitive_values)
    console_handler = logging.StreamHandler()
    for handler in (console_handler, file_handler):
        handler.setFormatter(formatter)
        handler.addFilter(redactor)

    logger = logging.getLogger("src.ingestion")
    logger.handlers.clear()
    logger.setLevel(getattr(logging, config.level))
    logger.propagate = False
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    return logger
