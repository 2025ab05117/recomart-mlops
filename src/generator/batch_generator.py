"""Orchestrate one synthetic e-commerce batch from MovieLens 100K."""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Sequence

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.generator.clickstream_generator import generate_clickstream
from src.generator.errors import GeneratorError, OutputPublicationError
from src.generator.generation_support import write_csv, write_json_array
from src.generator.generator_config import GeneratorConfig
from src.generator.movielens_loader import load_movielens_data
from src.generator.popularity_generator import generate_popularity
from src.generator.products_generator import generate_products
from src.generator.purchase_generator import generate_purchases
from src.generator.users_generator import generate_users

LOGGER = logging.getLogger(__name__)
DEFAULT_CONFIG_PATH = Path("configs/generator.yaml")
OUTPUT_NAMES = (
    "users.csv",
    "products.json",
    "clickstream.csv",
    "purchasehistory.csv",
    "popularity.json",
)


@dataclass(frozen=True)
class BatchGenerationResult:
    """Record counts and location for a successfully generated batch."""

    output_directory: Path
    users_count: int
    products_count: int
    clickstream_count: int
    purchases_count: int
    popularity_count: int


class BatchGenerator:
    """Coordinate focused generators and publish incoming datasets."""

    def __init__(self, config: GeneratorConfig) -> None:
        """Initialize the batch generator with validated settings."""
        self._config = config

    def generate(self) -> BatchGenerationResult:
        """Generate and publish all five required incoming datasets.

        Returns:
            Output location and generated record counts.

        Raises:
            GeneratorError: If source loading or publication fails.
            ValueError: If generated time constraints are inconsistent.
        """
        config = self._config
        _validate_output_targets(config)
        LOGGER.info(
            "Starting synthetic batch generation",
            extra={
                "event": "batch_generation_started",
                "source_directory": str(config.source_directory),
                "output_directory": str(config.output_directory),
                "random_seed": config.random_seed,
            },
        )
        source = load_movielens_data(
            config.source_directory,
            nested_directory_name=config.nested_directory_name,
        )
        users = generate_users(source.users, config)
        products, product_records = generate_products(
            source.items, source.ratings, source.genres, config
        )
        clickstream, final_click_times = generate_clickstream(
            source.ratings, config
        )
        purchases = generate_purchases(
            source.ratings, products, final_click_times, config
        )
        popularity = generate_popularity(products, config)

        output = config.output_directory
        write_csv(
            users,
            output / "users.csv",
            overwrite=config.overwrite_existing,
        )
        write_json_array(
            product_records,
            output / "products.json",
            overwrite=config.overwrite_existing,
        )
        write_csv(
            clickstream,
            output / "clickstream.csv",
            overwrite=config.overwrite_existing,
        )
        write_csv(
            purchases,
            output / "purchasehistory.csv",
            overwrite=config.overwrite_existing,
        )
        write_json_array(
            popularity,
            output / "popularity.json",
            overwrite=config.overwrite_existing,
        )

        result = BatchGenerationResult(
            output,
            len(users),
            len(products),
            len(clickstream),
            len(purchases),
            len(popularity),
        )
        LOGGER.info(
            "Completed synthetic batch generation",
            extra={
                "event": "batch_generation_completed",
                "users_count": result.users_count,
                "products_count": result.products_count,
                "clickstream_count": result.clickstream_count,
                "purchases_count": result.purchases_count,
                "popularity_count": result.popularity_count,
            },
        )
        return result


def main(arguments: Sequence[str] | None = None) -> int:
    """Run generation from the command line and return an exit code."""
    parser = argparse.ArgumentParser(
        description="Generate incoming datasets from MovieLens 100K."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="YAML path relative to the repository root.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Override the configured deterministic seed.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Explicitly replace existing local incoming files.",
    )
    parsed = parser.parse_args(arguments)
    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s %(levelname)s %(name)s "
            "event=%(event)s %(message)s"
        ),
    )
    try:
        config = GeneratorConfig.from_yaml(parsed.config)
        config = replace(
            config,
            random_seed=(
                parsed.seed
                if parsed.seed is not None
                else config.random_seed
            ),
            overwrite_existing=(
                parsed.overwrite or config.overwrite_existing
            ),
        )
        BatchGenerator(config).generate()
    except (GeneratorError, ValueError) as exc:
        LOGGER.error(
            "Synthetic batch generation failed",
            extra={"event": "batch_generation_failed"},
            exc_info=exc,
        )
        return 1
    return 0


def _validate_output_targets(config: GeneratorConfig) -> None:
    if config.overwrite_existing:
        return
    existing = [
        config.output_directory / name
        for name in OUTPUT_NAMES
        if (config.output_directory / name).exists()
    ]
    if existing:
        raise OutputPublicationError(
            "Incoming outputs are immutable; existing files: "
            + ", ".join(str(path) for path in existing)
        )


if __name__ == "__main__":
    raise SystemExit(main())
