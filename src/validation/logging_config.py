"""Structured console and rotating-file logging for validation."""

from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import datetime, timezone
from typing import Iterable

from src.validation.config import ValidationLogConfig
from src.validation.errors import ValidationConfigurationError

FIELDS = (
    "batch_id",
    "validation_run_id",
    "correlation_id",
    "dataset_type",
    "rule_id",
    "operation",
    "status",
    "records_checked",
    "failed_record_count",
    "duration_ms",
)


class ValidationJsonFormatter(logging.Formatter):
    """Format validation events as JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        """Create a stable machine-readable record."""
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(
                record.created, timezone.utc
            ).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "log_level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }
        for name in FIELDS:
            value = getattr(record, name, None)
            if value is not None:
                payload[name] = value
        if record.exc_info:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False)


class ValidationSecretFilter(logging.Filter):
    """Redact configured secret values before output."""

    def __init__(self, secrets: Iterable[str]) -> None:
        """Retain only non-empty secret values."""
        super().__init__()
        self._secrets = tuple(secret for secret in secrets if secret)

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact message arguments without logging environment state."""
        message = record.getMessage()
        for secret in self._secrets:
            message = message.replace(secret, "[REDACTED]")
        record.msg = message
        record.args = ()
        return True


def configure_validation_logging(
    config: ValidationLogConfig,
    *,
    sensitive_values: Iterable[str] = (),
) -> logging.Logger:
    """Configure validation console and rotating file handlers."""
    try:
        config.directory.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            config.directory / config.filename,
            maxBytes=config.max_bytes,
            backupCount=config.backup_count,
            encoding="utf-8",
        )
    except OSError as exc:
        raise ValidationConfigurationError(
            f"Unable to initialize validation logging: {config.directory}"
        ) from exc
    console_handler = logging.StreamHandler()
    formatter = ValidationJsonFormatter()
    secret_filter = ValidationSecretFilter(sensitive_values)
    for handler in (console_handler, file_handler):
        handler.setFormatter(formatter)
        handler.addFilter(secret_filter)
    logger = logging.getLogger("src.validation")
    for existing in logger.handlers:
        existing.close()
    logger.handlers.clear()
    logger.setLevel(getattr(logging, config.level))
    logger.propagate = False
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    return logger
