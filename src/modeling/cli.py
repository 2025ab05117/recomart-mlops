"""Command-line entry point for reproducible model training."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Sequence

from src.modeling.config import load_modeling_config
from src.modeling.errors import TrainingError
from src.modeling.logging_config import configure_logging
from src.modeling.runner import TrainingRunner

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build documented model-training arguments."""
    parser = argparse.ArgumentParser(description="Train RecoMart recommenders")
    parser.add_argument(
        "--algorithm", choices=("collaborative", "content", "all"),
        default="all",
    )
    parser.add_argument("--feature-batch-id")
    parser.add_argument("--top-k", type=int)
    parser.add_argument(
        "--config", type=Path, default=Path("configs/modeling.yaml")
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run selected training algorithms once."""
    args = build_parser().parse_args(argv)
    try:
        config = load_modeling_config(
            args.config, overrides={"top_k": args.top_k}
        )
        configure_logging(config)
        TrainingRunner(config).run(
            algorithm=args.algorithm,
            feature_batch_id=args.feature_batch_id,
        )
        return 0
    except TrainingError as exc:
        logging.basicConfig(level=logging.ERROR)
        LOGGER.error("Model training failed", exc_info=exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
