"""Structured console and rotating preparation logging."""

from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import datetime, timezone

from src.preparation.config import PreparationConfig

FIELDS = (
    "batch_id", "preparation_run_id", "correlation_id", "dataset_type",
    "operation", "status", "records_in", "records_out", "records_removed",
    "duration_ms",
)


class JsonFormatter(logging.Formatter):
    """Render stable JSON log records."""

    def format(self, record: logging.LogRecord) -> str:
        """Format one log record."""
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(
                record.created, timezone.utc
            ).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "log_level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }
        for field in FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload)


def configure_logging(config: PreparationConfig) -> None:
    """Configure console and bounded rotating file output."""
    config.log_directory.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            config.log_directory / config.log_filename,
            maxBytes=config.log_max_bytes,
            backupCount=config.log_backup_count,
            encoding="utf-8",
        ),
    ]
    formatter = JsonFormatter()
    for handler in handlers:
        handler.setFormatter(formatter)
    logger = logging.getLogger("src.preparation")
    for handler in logger.handlers:
        handler.close()
    logger.handlers.clear()
    logger.handlers.extend(handlers)
    logger.setLevel(getattr(logging, config.log_level))
    logger.propagate = False
