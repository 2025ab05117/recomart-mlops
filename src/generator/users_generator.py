"""Synthetic e-commerce user generation from MovieLens users."""

from __future__ import annotations

import logging
from datetime import timedelta

import pandas as pd

from src.generator.generation_support import create_random
from src.generator.generator_config import GeneratorConfig

LOGGER = logging.getLogger(__name__)
OUTPUT_COLUMNS = [
    "user_id",
    "age",
    "gender",
    "occupation",
    "zipcode",
    "registration_date",
    "customer_segment",
]


def generate_users(
    source_users: pd.DataFrame, config: GeneratorConfig
) -> pd.DataFrame:
    """Create deterministic customer attributes while preserving user IDs."""
    randomizer = create_random(config.random_seed, "users")
    lookback_days = config.registration_lookback_years * 365
    result = source_users.copy()
    result["registration_date"] = [
        (
            config.reference_time
            - timedelta(days=randomizer.randint(0, lookback_days))
        ).date().isoformat()
        for _ in range(len(result))
    ]
    result["customer_segment"] = [
        randomizer.choice(config.customer_segments)
        for _ in range(len(result))
    ]
    result = result.loc[:, OUTPUT_COLUMNS]
    LOGGER.info(
        "Generated users",
        extra={"event": "users_generated", "record_count": len(result)},
    )
    return result
