"""Synthetic purchase history generation from high MovieLens ratings."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd

from src.generator.generation_support import (
    create_random,
    deterministic_uuid,
    format_utc_timestamp,
)
from src.generator.generator_config import GeneratorConfig

LOGGER = logging.getLogger(__name__)
OUTPUT_COLUMNS = [
    "order_id",
    "user_id",
    "product_id",
    "quantity",
    "amount",
    "rating",
    "purchase_timestamp",
]


def generate_purchases(
    ratings: pd.DataFrame,
    products: pd.DataFrame,
    final_click_times: dict[int, datetime],
    config: GeneratorConfig,
) -> pd.DataFrame:
    """Create purchases for ratings of four or five after their click event."""
    randomizer = create_random(config.random_seed, "purchases")
    prices = products.set_index("product_id")["price"].to_dict()
    records: list[dict[str, object]] = []
    qualifying = ratings.reset_index(drop=True)
    qualifying = qualifying[qualifying["rating"] >= 4]
    minimum_delay = config.purchase_delay_min_minutes * 60

    for row in qualifying.itertuples(index=True):
        source_row_id = int(row.Index)
        click_time = final_click_times[source_row_id]
        seconds_until_reference = int(
            (config.reference_time - click_time).total_seconds()
        )
        maximum_delay = min(
            config.purchase_delay_max_minutes * 60,
            seconds_until_reference,
        )
        if maximum_delay < minimum_delay:
            raise ValueError(
                "Purchase click does not allow the configured minimum delay."
            )
        purchase_time = click_time + timedelta(
            seconds=randomizer.randint(minimum_delay, maximum_delay)
        )
        quantity = randomizer.randint(1, 3)
        unit_price = float(prices[int(row.product_id)])
        records.append(
            {
                "order_id": deterministic_uuid(
                    config.random_seed, "order", str(source_row_id)
                ),
                "user_id": int(row.user_id),
                "product_id": int(row.product_id),
                "quantity": quantity,
                "amount": round(quantity * unit_price, 2),
                "rating": int(row.rating),
                "purchase_timestamp": format_utc_timestamp(purchase_time),
            }
        )
    result = pd.DataFrame(records, columns=OUTPUT_COLUMNS)
    result = result.sort_values(
        ["purchase_timestamp", "order_id"], kind="stable"
    ).reset_index(drop=True)
    LOGGER.info(
        "Generated purchases",
        extra={"event": "purchases_generated", "record_count": len(result)},
    )
    return result
