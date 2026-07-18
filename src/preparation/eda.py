"""Deterministic exploratory analysis and static plot generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from src.preparation.config import PreparationConfig
from src.preparation.errors import EdaGenerationError
from src.preparation.transformations import PreparedData

PLOTS = (
    "interaction_type_distribution.png",
    "user_interaction_distribution.png",
    "item_popularity_distribution.png",
    "rating_distribution.png",
    "category_distribution.png",
    "price_distribution.png",
    "user_item_sparsity_heatmap.png",
    "numerical_correlation_heatmap.png",
    "interactions_over_time.png",
)


def generate_eda(
    prepared: PreparedData,
    directory: Path,
    config: PreparationConfig,
    *,
    batch_id: str,
    preparation_run_id: str,
    generated_at: str,
) -> tuple[dict[str, Any], list[Path]]:
    """Create the EDA JSON summary and all required static plots."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        sns.set_theme(style="whitegrid")
        interactions = prepared.interactions
        aggregate = prepared.aggregated
        products = prepared.products
        counts = interactions["interaction_type"].value_counts()
        rating_counts = (
            interactions["explicit_rating"].dropna().astype(int)
            .value_counts().sort_index()
        )
        top_products = (
            aggregate.groupby("product_id")["interaction_count"].sum()
            .nlargest(config.top_items)
        )
        top_users = (
            interactions.groupby("user_id").size().nlargest(config.top_items)
        )
        summary = {
            "batch_id": batch_id,
            "preparation_run_id": preparation_run_id,
            "generated_at": generated_at,
            "users": int(len(prepared.users)),
            "products": int(len(products)),
            "interactions": int(len(interactions)),
            "unique_user_product_pairs": (
                prepared.matrix_statistics["observed_user_product_pairs"]
            ),
            "possible_user_product_pairs": (
                prepared.matrix_statistics["possible_user_product_pairs"]
            ),
            "density": prepared.matrix_statistics["density"],
            "sparsity": prepared.matrix_statistics["sparsity"],
            "interaction_type_counts": {
                str(key): int(value) for key, value in counts.items()
            },
            "rating_distribution": {
                str(key): int(value) for key, value in rating_counts.items()
            },
            "top_products": [
                {"product_id": int(key), "interaction_count": int(value)}
                for key, value in top_products.items()
            ],
            "top_users": [
                {"user_id": int(key), "interaction_count": int(value)}
                for key, value in top_users.items()
            ],
            "train_records": len(prepared.train),
            "validation_records": len(prepared.validation),
            "test_records": len(prepared.test),
            "price_statistics": _describe(products["price"]),
            "interactions_per_user": _describe(
                interactions.groupby("user_id").size()
            ),
            "cold_start": {
                key: value for key, value in prepared.split_metadata.items()
                if key.startswith("cold_start")
            },
        }
        paths: list[Path] = []
        paths.append(_bar(counts, directory / PLOTS[0],
                          "Interaction Type Distribution", "Interaction Type",
                          "Observed Events", config.plot_dpi))
        paths.append(_hist(
            interactions.groupby("user_id").size(), directory / PLOTS[1],
            "Interactions per User", "Interactions per User", "Users",
            config.plot_dpi, log_y=True,
        ))
        item_counts = interactions.groupby("product_id").size().sort_values(
            ascending=False
        ).reset_index(drop=True)
        paths.append(_line(
            item_counts, directory / PLOTS[2], "Item Popularity Long Tail",
            "Product Rank", "Observed Interactions", config.plot_dpi,
            log_y=True,
        ))
        paths.append(_hist(
            interactions["explicit_rating"].dropna(), directory / PLOTS[3],
            "Explicit Purchase Rating Distribution", "Rating (1–5)",
            "Purchases", config.plot_dpi, bins=np.arange(0.5, 6, 1),
        ))
        category_counts = products["category"].value_counts().head(
            config.top_items
        )
        paths.append(_bar(
            category_counts, directory / PLOTS[4],
            f"Top {config.top_items} Product Categories", "Category",
            "Products", config.plot_dpi, rotate=True,
        ))
        paths.append(_hist(
            products["price"], directory / PLOTS[5],
            "Product Price Distribution", "Price", "Products",
            config.plot_dpi,
        ))
        paths.append(_sparsity_heatmap(prepared, directory / PLOTS[6], config))
        paths.append(_correlation_heatmap(prepared, directory / PLOTS[7], config))
        hourly = interactions.set_index("event_timestamp").resample("h").size()
        paths.append(_timeline(hourly, directory / PLOTS[8], config.plot_dpi))
        (directory / "eda_summary.json").write_text(
            json.dumps(summary, indent=2, default=str), encoding="utf-8"
        )
        return summary, paths
    except (OSError, ValueError, TypeError) as exc:
        raise EdaGenerationError("Unable to generate EDA artifacts.") from exc
    finally:
        plt.close("all")


def _save(fig: plt.Figure, path: Path, dpi: int) -> Path:
    fig.tight_layout()
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return path


def _bar(series: pd.Series, path: Path, title: str, xlabel: str,
         ylabel: str, dpi: int, rotate: bool = False) -> Path:
    fig, axis = plt.subplots(figsize=(10, 6))
    series.plot(kind="bar", ax=axis, color="#3B82F6")
    axis.set(title=title, xlabel=xlabel, ylabel=ylabel)
    axis.tick_params(axis="x", rotation=45 if rotate else 0)
    return _save(fig, path, dpi)


def _hist(series: pd.Series, path: Path, title: str, xlabel: str,
          ylabel: str, dpi: int, bins: Any = 30,
          log_y: bool = False) -> Path:
    fig, axis = plt.subplots(figsize=(10, 6))
    axis.hist(series.dropna(), bins=bins, color="#10B981", edgecolor="white")
    axis.set(title=title, xlabel=xlabel, ylabel=ylabel)
    if log_y:
        axis.set_yscale("log")
    return _save(fig, path, dpi)


def _line(series: pd.Series, path: Path, title: str, xlabel: str,
          ylabel: str, dpi: int, log_y: bool = False) -> Path:
    fig, axis = plt.subplots(figsize=(10, 6))
    axis.plot(np.arange(1, len(series) + 1), series, color="#8B5CF6")
    axis.set(title=title, xlabel=xlabel, ylabel=ylabel)
    if log_y:
        axis.set_yscale("log")
    return _save(fig, path, dpi)


def _sparsity_heatmap(
    prepared: PreparedData, path: Path, config: PreparationConfig
) -> Path:
    active_users = prepared.interactions["user_id"].value_counts().head(
        config.heatmap_top_users
    ).index
    popular_products = prepared.interactions["product_id"].value_counts().head(
        config.heatmap_top_products
    ).index
    sample = prepared.aggregated[
        prepared.aggregated["user_id"].isin(active_users)
        & prepared.aggregated["product_id"].isin(popular_products)
    ].pivot(index="user_id", columns="product_id", values="implicit_score")
    sample = sample.reindex(
        index=active_users, columns=popular_products, fill_value=0
    ).fillna(0)
    fig, axis = plt.subplots(figsize=(14, 10))
    sns.heatmap(sample, cmap="YlGnBu", ax=axis, cbar_kws={"label": "Implicit score"})
    axis.set_title("Sampled User–Item Interaction Intensity (Top Active/Popular)")
    axis.set(xlabel="Product ID", ylabel="User ID")
    return _save(fig, path, config.plot_dpi)


def _correlation_heatmap(
    prepared: PreparedData, path: Path, config: PreparationConfig
) -> Path:
    aggregate = prepared.aggregated.merge(
        prepared.users[["user_id", "age"]], on="user_id", how="left"
    ).merge(
        prepared.products[[
            "product_id", "price", "average_rating", "total_ratings",
            "popularity_score",
        ]],
        on="product_id", how="left",
    )
    columns = [
        "age", "price", "average_rating", "total_ratings",
        "popularity_score", "total_quantity", "total_spend",
        "implicit_score", "interaction_count", "purchase_count",
    ]
    correlation = aggregate[columns].corr(numeric_only=True).dropna(
        how="all"
    ).dropna(axis=1, how="all")
    fig, axis = plt.subplots(figsize=(11, 9))
    sns.heatmap(correlation, cmap="coolwarm", center=0, annot=True,
                fmt=".2f", ax=axis)
    axis.set_title("Numerical Feature Correlation (Identifiers Excluded)")
    return _save(fig, path, config.plot_dpi)


def _timeline(series: pd.Series, path: Path, dpi: int) -> Path:
    fig, axis = plt.subplots(figsize=(12, 6))
    series.plot(ax=axis, color="#F97316")
    axis.set(title="Hourly Interaction Volume", xlabel="UTC Time",
             ylabel="Observed Interactions per Hour")
    return _save(fig, path, dpi)


def _describe(series: pd.Series) -> dict[str, float]:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return {
        "minimum": float(values.min()) if len(values) else 0.0,
        "maximum": float(values.max()) if len(values) else 0.0,
        "mean": float(values.mean()) if len(values) else 0.0,
        "median": float(values.median()) if len(values) else 0.0,
        "p25": float(values.quantile(0.25)) if len(values) else 0.0,
        "p75": float(values.quantile(0.75)) if len(values) else 0.0,
        "p95": float(values.quantile(0.95)) if len(values) else 0.0,
    }
