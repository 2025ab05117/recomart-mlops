"""Command-line entry point for RecoMart data versioning and lineage."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from src.versioning.config import load_versioning_config
from src.versioning.errors import VersioningError
from src.versioning.logging_config import configure_logging
from src.versioning.service import VersioningService

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Create the supported versioning command-line interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage")
    parser.add_argument("--batch-id")
    parser.add_argument("--register", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--generate-lineage", action="store_true")
    parser.add_argument("--generate-registry", action="store_true")
    parser.add_argument(
        "--config", type=Path, default=Path("configs/versioning.yaml")
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute requested operations once and return an operational exit code."""
    args = build_parser().parse_args(argv)
    try:
        config = load_versioning_config(args.config)
        configure_logging(config, args.log_level)
        service = VersioningService(config)
        any_action = any((
            args.register, args.verify, args.generate_lineage,
            args.generate_registry,
        ))
        if args.register or args.generate_registry or not any_action:
            service.register(stage=args.stage, batch_id=args.batch_id)
        lineage = None
        if args.generate_lineage or not any_action:
            lineage = service.generate_lineage()
        if args.generate_registry or args.generate_lineage or not any_action:
            service.generate_summary(lineage)
        verification = None
        if args.verify or not any_action:
            verification = service.verify(stage=args.stage)
        if verification is not None:
            LOGGER.info(
                json.dumps(verification, default=str),
                extra={"operation": "cli", "status": verification["status"]},
            )
            return 0 if verification["status"] == "SUCCESS" else 1
        return 0
    except VersioningError as exc:
        LOGGER.exception(
            "Versioning failed",
            extra={"operation": "cli", "status": "FAILED"},
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
