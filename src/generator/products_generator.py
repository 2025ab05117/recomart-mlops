"""Synthetic e-commerce product generation from MovieLens movies."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from src.generator.generation_support import create_random
from src.generator.generator_config import GeneratorConfig

LOGGER = logging.getLogger(__name__)
OUTPUT_COLUMNS = [
    "product_id",
    "product_name",
    "category",
    "release_date",
    "price",
    "brand",
    "average_rating",
    "total_ratings",
]


def generate_products(
    source_items: pd.DataFrame,
    ratings: pd.DataFrame,
    genres: tuple[str, ...],
    config: GeneratorConfig,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Convert movies to products and calculate their rating statistics."""
    randomizer = create_random(config.random_seed, "products")
    statistics = ratings.groupby("product_id", as_index=False).agg(
        average_rating=("rating", "mean"),
        total_ratings=("rating", "size"),
    )
    result = source_items.copy()
    result["category"] = result.apply(
        lambda row: _first_genre(row, genres), axis=1
    )
    result["price"] = [
        round(
            randomizer.uniform(config.minimum_price, config.maximum_price), 2
        )
        for _ in range(len(result))
    ]
    result["brand"] = [
        randomizer.choice(config.brands) for _ in range(len(result))
    ]
    result = result.merge(statistics, on="product_id", how="left")
    result["average_rating"] = result["average_rating"].fillna(0.0).round(4)
    result["total_ratings"] = result["total_ratings"].fillna(0).astype(int)
    result = result.loc[:, OUTPUT_COLUMNS].sort_values("product_id")
    records = [
        {
            "product_id": int(row.product_id),
            "product_name": str(row.product_name),
            "category": str(row.category),
            "release_date": (
                None if pd.isna(row.release_date) else str(row.release_date)
            ),
            "price": float(row.price),
            "brand": str(row.brand),
            "average_rating": float(row.average_rating),
            "total_ratings": int(row.total_ratings),
        }
        for row in result.itertuples(index=False)
    ]
    LOGGER.info(
        "Generated products",
        extra={"event": "products_generated", "record_count": len(result)},
    )
    return result, records


def _first_genre(row: pd.Series, genres: tuple[str, ...]) -> str:
    for genre in genres:
        if int(row[genre]) == 1:
            return genre
    return "unknown"
