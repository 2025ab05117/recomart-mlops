"""Command-line entry point for one RecoMart validation run."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from typing import Sequence

from src.validation.batch_repository import (
    LocalRawBatchRepository,
    RawBatchRepository,
    S3RawBatchRepository,
)
from src.validation.config import (
    DEFAULT_CONFIG_PATH,
    ValidationConfig,
    load_validation_config,
)
from src.validation.errors import ValidationError
from src.validation.logging_config import configure_validation_logging
from src.validation.validation_runner import ValidationRunner

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the documented validation CLI parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Profile and validate one manifest-resolved RecoMart raw batch."
        )
    )
    parser.add_argument("--batch-id")
    parser.add_argument("--raw-path")
    parser.add_argument("--validated-path")
    parser.add_argument("--quarantine-path")
    parser.add_argument("--report-path")
    parser.add_argument("--storage", choices=("local", "s3"), default="local")
    parser.add_argument("--bucket")
    parser.add_argument("--prefix", default="raw")
    parser.add_argument("--endpoint-url")
    parser.add_argument("--region")
    parser.add_argument("--profile")
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG_PATH
    )
    parser.add_argument(
        "--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR")
    )
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    """Execute one validation batch and return the documented exit code."""
    parsed = build_parser().parse_args(arguments)
    try:
        config = load_validation_config(
            parsed.config,
            overrides={
                "raw_path": parsed.raw_path,
                "validated_path": parsed.validated_path,
                "quarantine_path": parsed.quarantine_path,
                "report_path": parsed.report_path,
                "log_level": parsed.log_level,
            },
        )
        configure_validation_logging(
            config.logging,
            sensitive_values=_credential_values(),
        )
        repository = create_repository(
            config=config,
            storage_type=parsed.storage,
            bucket=parsed.bucket,
            prefix=parsed.prefix,
            endpoint_url=parsed.endpoint_url,
            region=parsed.region,
            profile=parsed.profile,
        )
        result = ValidationRunner(
            config=config, repository=repository
        ).run(batch_id=parsed.batch_id)
        return result.exit_code(strict_quality=config.strict_quality)
    except ValidationError as exc:
        _ensure_fallback_logging()
        LOGGER.error(
            "Validation command failed",
            extra={"operation": "validation_cli", "status": "FAILED"},
            exc_info=exc,
        )
        return 2


def create_repository(
    *,
    config: ValidationConfig,
    storage_type: str,
    bucket: str | None,
    prefix: str,
    endpoint_url: str | None,
    region: str | None,
    profile: str | None,
) -> RawBatchRepository:
    """Create a local or S3 manifest-first raw repository."""
    if storage_type == "local":
        return LocalRawBatchRepository(config.raw_path)
    return S3RawBatchRepository(
        bucket=bucket or os.environ.get("RECOMART_S3_BUCKET", ""),
        prefix=prefix,
        endpoint_url=(
            endpoint_url or os.environ.get("RECOMART_S3_ENDPOINT_URL")
        ),
        region=region or os.environ.get("AWS_DEFAULT_REGION"),
        profile=profile or os.environ.get("AWS_PROFILE"),
    )


def _credential_values() -> tuple[str, ...]:
    return tuple(
        os.environ.get(name, "")
        for name in (
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
        )
    )


def _ensure_fallback_logging() -> None:
    if not logging.getLogger("src.validation").handlers:
        logging.basicConfig(
            level=logging.ERROR,
            format=(
                '{"timestamp":"%(asctime)s","log_level":"%(levelname)s",'
                '"module":"%(name)s","message":"%(message)s"}'
            ),
        )


if __name__ == "__main__":
    raise SystemExit(main())
