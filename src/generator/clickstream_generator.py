"""Synthetic clickstream generation from MovieLens rating interactions."""

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
EVENT_MAPPING: dict[int, tuple[str, ...]] = {
    1: ("View",),
    2: ("View",),
    3: ("View",),
    4: ("View", "AddToCart"),
    5: ("View", "Wishlist", "AddToCart"),
}
OUTPUT_COLUMNS = [
    "event_id",
    "user_id",
    "product_id",
    "event_type",
    "timestamp",
    "session_id",
]


def generate_clickstream(
    ratings: pd.DataFrame, config: GeneratorConfig
) -> tuple[pd.DataFrame, dict[int, datetime]]:
    """Expand ratings into chronologically ordered, sessionized events.

    Returns:
        Clickstream records and final click time keyed by source rating row.
    """
    randomizer = create_random(config.random_seed, "clickstream")
    window_start = config.reference_time - timedelta(
        hours=config.clickstream_lookback_hours
    )
    latest_interaction = config.reference_time - timedelta(
        minutes=config.purchase_delay_min_minutes + 1
    )
    available_seconds = int(
        (latest_interaction - window_start).total_seconds()
    )
    if available_seconds <= 0:
        raise ValueError(
            "Clickstream window must exceed the minimum purchase delay."
        )
    working = ratings.reset_index(drop=True).copy()
    working["source_row_id"] = working.index
    working["interaction_offset"] = [
        randomizer.randint(0, available_seconds)
        for _ in range(len(working))
    ]
    working = working.sort_values(
        ["user_id", "interaction_offset", "source_row_id"]
    )

    events: list[dict[str, object]] = []
    final_event_times: dict[int, datetime] = {}
    inactivity = timedelta(minutes=config.session_inactivity_minutes)
    for user_id, user_rows in working.groupby("user_id", sort=True):
        previous_time: datetime | None = None
        session_number = 0
        session_id = ""
        for row in user_rows.itertuples(index=False):
            interaction_time = window_start + timedelta(
                seconds=int(row.interaction_offset)
            )
            if (
                previous_time is None
                or interaction_time - previous_time > inactivity
            ):
                session_number += 1
                session_id = deterministic_uuid(
                    config.random_seed,
                    "session",
                    f"{int(user_id)}:{session_number}",
                )
            event_types = EVENT_MAPPING[int(row.rating)]
            final_time = interaction_time
            for position, event_type in enumerate(event_types):
                event_time = interaction_time + timedelta(seconds=position * 30)
                final_time = event_time
                events.append(
                    {
                        "event_id": deterministic_uuid(
                            config.random_seed,
                            "event",
                            f"{int(row.source_row_id)}:{position}",
                        ),
                        "user_id": int(row.user_id),
                        "product_id": int(row.product_id),
                        "event_type": event_type,
                        "timestamp": format_utc_timestamp(event_time),
                        "session_id": session_id,
                    }
                )
            final_event_times[int(row.source_row_id)] = final_time
            previous_time = interaction_time

    result = pd.DataFrame(events, columns=OUTPUT_COLUMNS)
    result = result.sort_values(
        ["timestamp", "user_id", "product_id", "event_id"], kind="stable"
    ).reset_index(drop=True)
    LOGGER.info(
        "Generated clickstream",
        extra={
            "event": "clickstream_generated",
            "record_count": len(result),
            "session_count": result["session_id"].nunique(),
        },
    )
    return result, final_event_times
