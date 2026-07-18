"""Structured rotating model-training logs."""

from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import datetime, timezone

from src.modeling.config import ModelingConfig


class JsonFormatter(logging.Formatter):
    """Format model events as JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        """Return stable timestamped JSON."""
        payload = {
            "timestamp": datetime.fromtimestamp(
                record.created, timezone.utc
            ).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "log_level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }
        for field in (
            "model_run_id", "feature_batch_id", "model_name", "operation",
            "status", "duration_ms",
        ):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(payload)


def configure_logging(config: ModelingConfig) -> None:
    """Configure console and rotating file logging."""
    config.log_directory.mkdir(parents=True, exist_ok=True)
    handlers = [
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            config.log_directory / config.log_filename,
            maxBytes=config.log_max_bytes,
            backupCount=config.log_backup_count,
            encoding="utf-8",
        ),
    ]
    for handler in handlers:
        handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("src.modeling")
    logger.handlers.clear()
    logger.handlers.extend(handlers)
    logger.setLevel(getattr(logging, config.log_level))
    logger.propagate = False
