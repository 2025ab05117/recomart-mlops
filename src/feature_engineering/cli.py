"""CLI for database initialization and one feature-engineering run."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Sequence

from src.feature_engineering.config import load_feature_config
from src.feature_engineering.errors import FeatureEngineeringError
from src.feature_engineering.logging_config import configure_logging
from src.feature_engineering.runner import FeatureRunner

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the documented feature CLI."""
    parser = argparse.ArgumentParser(description="Generate RecoMart features")
    parser.add_argument("--batch-id")
    parser.add_argument("--feature-batch-id")
    parser.add_argument("--prepared-path", type=Path)
    parser.add_argument("--output-path", type=Path)
    parser.add_argument(
        "--config", type=Path,
        default=Path("configs/feature_engineering.yaml"),
    )
    parser.add_argument("--database-url")
    parser.add_argument("--source-split", choices=("train", "all"))
    parser.add_argument("--skip-parquet", action="store_true")
    parser.add_argument("--initialize-database", action="store_true")
    parser.add_argument(
        "--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR")
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run initialization or feature generation and map failures to exit two."""
    args = build_parser().parse_args(argv)
    try:
        config = load_feature_config(args.config, overrides={
            "prepared_path": args.prepared_path,
            "output_path": args.output_path,
            "database_url": args.database_url,
            "source_split": args.source_split,
            "log_level": args.log_level,
        })
        configure_logging(config)
        runner = FeatureRunner(config)
        if args.initialize_database:
            runner.initialize_database()
        else:
            runner.run(
                batch_id=args.batch_id,
                feature_batch_id=args.feature_batch_id,
                write_parquet=not args.skip_parquet,
            )
        return 0
    except FeatureEngineeringError as exc:
        logging.basicConfig(level=logging.ERROR)
        LOGGER.error("Feature command failed", exc_info=exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
