"""External-style product popularity response generation."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from src.generator.generation_support import (
    create_random,
    format_utc_timestamp,
)
from src.generator.generator_config import GeneratorConfig

LOGGER = logging.getLogger(__name__)


def generate_popularity(
    products: pd.DataFrame, config: GeneratorConfig
) -> list[dict[str, Any]]:
    """Calculate weighted normalized popularity and simulated trend."""
    randomizer = create_random(config.random_seed, "popularity")
    counts = products["total_ratings"].astype(float)
    count_min = float(counts.min())
    count_range = float(counts.max()) - count_min
    updated_at = format_utc_timestamp(config.reference_time)
    records: list[dict[str, Any]] = []
    for row in products.sort_values("product_id").itertuples(index=False):
        average = float(row.average_rating)
        rating_score = max(0.0, min(100.0, ((average - 1.0) / 4.0) * 100))
        count_score = (
            0.0
            if count_range == 0
            else ((float(row.total_ratings) - count_min) / count_range) * 100
        )
        score = round(
            max(0.0, min(100.0, 0.60 * rating_score + 0.40 * count_score)),
            2,
        )
        previous = max(
            1.0, min(5.0, average + randomizer.uniform(-0.25, 0.25))
        )
        records.append(
            {
                "product_id": int(row.product_id),
                "popularity_score": score,
                "trend": "UP" if average >= previous else "DOWN",
                "updated_at": updated_at,
            }
        )
    LOGGER.info(
        "Generated popularity",
        extra={"event": "popularity_generated", "record_count": len(records)},
    )
    return records
