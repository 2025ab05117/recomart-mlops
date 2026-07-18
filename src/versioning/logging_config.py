"""Structured console and rotating-file logging for versioning."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any

from src.versioning.config import VersioningConfig


class JsonFormatter(logging.Formatter):
    """Format operational versioning logs as JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialize standard and contextual record fields."""
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace(
                "+00:00", "Z"
            ),
            "log_level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }
        for name in (
            "dataset_name", "dataset_version", "batch_id", "operation",
            "status", "checksum", "lineage_id",
        ):
            value = getattr(record, name, None)
            if value is not None:
                payload[name] = value
        return json.dumps(payload, default=str)


def configure_logging(config: VersioningConfig, level: str | None = None) -> None:
    """Configure root console and rotating file handlers once."""
    config.log_directory.mkdir(parents=True, exist_ok=True)
    formatter = JsonFormatter()
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel((level or config.log_level).upper())
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    file_handler = RotatingFileHandler(
        config.log_directory / config.log_filename,
        maxBytes=config.log_max_bytes,
        backupCount=config.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(console)
    root.addHandler(file_handler)
