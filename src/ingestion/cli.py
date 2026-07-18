"""Command-line entry point for one RecoMart ingestion batch."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from typing import Sequence

from src.ingestion.config import (
    DEFAULT_CONFIG_PATH,
    IngestionConfig,
    load_ingestion_config,
)
from src.ingestion.errors import ConfigurationError, IngestionError
from src.ingestion.ingestion_runner import IngestionRunner
from src.ingestion.logging_config import configure_ingestion_logging
from src.ingestion.storage import LocalStorage, RawStorage, S3Storage

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the documented ingestion CLI parser."""
    parser = argparse.ArgumentParser(
        description="Ingest RecoMart incoming sources into immutable raw storage."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--storage", choices=("local", "s3"))
    parser.add_argument("--input-path")
    parser.add_argument("--output-path")
    parser.add_argument("--batch-id")
    parser.add_argument("--popularity-api-url")
    parser.add_argument(
        "--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR")
    )
    parser.add_argument("--bucket")
    parser.add_argument("--prefix")
    parser.add_argument("--endpoint-url")
    parser.add_argument("--region")
    parser.add_argument("--profile")
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    """Load configuration, execute one batch, and return a process exit code."""
    parsed = build_parser().parse_args(arguments)
    overrides = {
        "storage": parsed.storage,
        "input_path": parsed.input_path,
        "output_path": parsed.output_path,
        "popularity_api_url": parsed.popularity_api_url,
        "log_level": parsed.log_level,
        "bucket": parsed.bucket,
        "prefix": parsed.prefix,
        "endpoint_url": parsed.endpoint_url,
        "region": parsed.region,
        "profile": parsed.profile,
    }
    try:
        config = load_ingestion_config(parsed.config, overrides=overrides)
        configure_ingestion_logging(
            config.logging,
            sensitive_values=_credential_values(),
        )
        storage = create_storage(config)
        result = IngestionRunner(config=config, storage=storage).run(
            batch_id=parsed.batch_id
        )
        return result.exit_code
    except (ConfigurationError, IngestionError) as exc:
        _ensure_fallback_logging()
        LOGGER.error(
            "Ingestion command failed",
            extra={"operation": "cli", "status": "FAILED"},
            exc_info=exc,
        )
        return 1


def create_storage(config: IngestionConfig) -> RawStorage:
    """Create the configured local or S3-compatible storage adapter."""
    if config.storage_type == "local":
        return LocalStorage(config.local_raw_path)
    if config.storage_type == "s3":
        return S3Storage(
            bucket=config.s3.bucket,
            prefix=config.s3.prefix,
            region=config.s3.region,
            endpoint_url=config.s3.endpoint_url,
            profile=config.s3.profile,
            max_attempts=config.s3.max_attempts,
            backoff_seconds=config.s3.backoff_seconds,
        )
    raise ConfigurationError(
        f"Unsupported storage type: {config.storage_type}"
    )


def _credential_values() -> tuple[str, ...]:
    names = (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
    )
    return tuple(os.environ.get(name, "") for name in names)


def _ensure_fallback_logging() -> None:
    if not logging.getLogger("src.ingestion").handlers:
        logging.basicConfig(
            level=logging.ERROR,
            format=(
                '{"timestamp":"%(asctime)s","log_level":"%(levelname)s",'
                '"module":"%(name)s","message":"%(message)s"}'
            ),
        )


if __name__ == "__main__":
    raise SystemExit(main())
