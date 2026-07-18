"""Command-line interface for one preparation execution."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Sequence

from src.preparation.config import load_preparation_config
from src.preparation.errors import PreparationError
from src.preparation.logging_config import configure_logging
from src.preparation.runner import PreparationRunner

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the documented preparation CLI parser."""
    parser = argparse.ArgumentParser(description="Prepare validated RecoMart data")
    parser.add_argument("--batch-id")
    parser.add_argument("--validated-path", type=Path)
    parser.add_argument("--output-path", type=Path)
    parser.add_argument("--report-path", type=Path)
    parser.add_argument(
        "--config", type=Path, default=Path("configs/preparation.yaml")
    )
    parser.add_argument(
        "--run-eda",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Generate EDA summaries and plots (default: true).",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default=None,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run preparation once and return zero or technical-failure code two."""
    args = build_parser().parse_args(argv)
    try:
        config = load_preparation_config(
            args.config,
            overrides={
                "validated_path": args.validated_path,
                "output_path": args.output_path,
                "report_path": args.report_path,
                "log_level": args.log_level,
            },
        )
        configure_logging(config)
        PreparationRunner(config).run(
            batch_id=args.batch_id, run_eda=args.run_eda
        )
        return 0
    except PreparationError as exc:
        logging.basicConfig(level=logging.ERROR)
        LOGGER.error("Preparation failed", exc_info=exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
