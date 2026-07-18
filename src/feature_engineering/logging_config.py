"""Credential-safe structured feature-engineering logging."""

from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import datetime, timezone

from src.feature_engineering.config import FeatureConfig

FIELDS = (
    "feature_batch_id", "source_batch_id", "correlation_id",
    "feature_group", "operation", "status", "records_in",
    "records_out", "duration_ms",
)


class JsonFormatter(logging.Formatter):
    """Render one structured JSON log line."""

    def format(self, record: logging.LogRecord) -> str:
        """Format without inspecting or emitting environment secrets."""
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
        return json.dumps(payload)


def configure_logging(config: FeatureConfig) -> None:
    """Configure console and rotating file JSON logs."""
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
    for handler in handlers:
        handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("src.feature_engineering")
    for old in logger.handlers:
        old.close()
    logger.handlers.clear()
    logger.handlers.extend(handlers)
    logger.setLevel(getattr(logging, config.log_level))
    logger.propagate = False
