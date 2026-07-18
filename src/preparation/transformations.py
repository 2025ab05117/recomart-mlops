"""Cleaning, encoding, normalization, interactions, matrices, and splitting."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.preprocessing import StandardScaler

from src.preparation.config import PreparationConfig
from src.preparation.errors import (
    DataSplitError,
    DatasetPreparationError,
    MatrixConstructionError,
)

REQUIRED = {
    "users": {"user_id", "age", "gender", "occupation", "zipcode",
              "registration_date", "customer_segment"},
    "products": {"product_id", "product_name", "category", "release_date",
                 "price", "brand", "average_rating", "total_ratings"},
    "clickstream": {"event_id", "user_id", "product_id", "event_type",
                    "timestamp", "session_id"},
    "purchasehistory": {"order_id", "user_id", "product_id", "quantity",
                        "amount", "rating", "purchase_timestamp"},
}


@dataclass
class PreparedData:
    """All in-memory prepared artifacts and reproducibility metadata."""

    users: pd.DataFrame
    products: pd.DataFrame
    interactions: pd.DataFrame
    aggregated: pd.DataFrame
    implicit_matrix: pd.DataFrame
    ratings_matrix: pd.DataFrame
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    encoder_metadata: dict[str, Any]
    scaler_metadata: dict[str, Any]
    cleaning_actions: list[dict[str, Any]]
    split_metadata: dict[str, Any]
    matrix_statistics: dict[str, Any]


def clean_datasets(
    frames: dict[str, pd.DataFrame],
    *,
    batch_id: str,
    reference_time: datetime,
    unknown: str,
) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]]]:
    """Clean validated frames without imputation or identifier reassignment."""
    cleaned: dict[str, pd.DataFrame] = {}
    actions: list[dict[str, Any]] = []
    for name, source in frames.items():
        frame = source.copy()
        frame.columns = [str(column).strip().lower() for column in frame.columns]
        missing = REQUIRED.get(name, set()).difference(frame.columns)
        if missing:
            raise DatasetPreparationError(
                f"{name} missing required columns: {sorted(missing)}"
            )
        for column in frame.select_dtypes(include=["object", "string"]).columns:
            frame[column] = frame[column].astype("string").str.strip()
        before = len(frame)
        frame = frame.drop_duplicates().reset_index(drop=True)
        actions.append({
            "dataset": name,
            "action": "remove_technical_duplicates",
            "records_before": before,
            "records_after": len(frame),
            "records_removed": before - len(frame),
        })
        frame["batch_id"] = batch_id
        cleaned[name] = frame

    users = cleaned["users"]
    users["user_id"] = pd.to_numeric(users["user_id"]).astype("int64")
    users["age"] = pd.to_numeric(users["age"]).astype("float64")
    users["gender"] = users["gender"].str.upper()
    users["occupation"] = users["occupation"].str.lower()
    users["customer_segment"] = users["customer_segment"].str.title()
    users["registration_date"] = pd.to_datetime(
        users["registration_date"], utc=True, errors="raise"
    )
    ref = pd.Timestamp(reference_time)
    users["user_registration_age_days"] = (
        ref - users["registration_date"]
    ).dt.total_seconds().div(86400).clip(lower=0)

    products = cleaned["products"]
    for column in ("product_id", "total_ratings"):
        products[column] = pd.to_numeric(products[column]).astype("int64")
    for column in ("price", "average_rating"):
        products[column] = pd.to_numeric(products[column]).astype("float64")
    for column in ("category", "brand"):
        products[column] = products[column].fillna(unknown).str.title()
    products["release_date"] = pd.to_datetime(
        products["release_date"], utc=True, errors="coerce"
    )
    products["product_age_days"] = (
        ref - products["release_date"]
    ).dt.total_seconds().div(86400).clip(lower=0)

    popularity = cleaned["popularity"]
    if not popularity.empty:
        for column in ("product_id", "total_ratings"):
            popularity[column] = pd.to_numeric(popularity[column]).astype("int64")
        for column in ("average_rating", "popularity_score"):
            popularity[column] = pd.to_numeric(popularity[column]).astype("float64")
        popularity["trend"] = popularity["trend"].str.upper()
        popularity["updated_at"] = pd.to_datetime(
            popularity["updated_at"], utc=True, errors="raise"
        )
        enrichment = popularity[["product_id", "popularity_score", "trend"]]
        products = products.merge(enrichment, on="product_id", how="left")
    else:
        products["popularity_score"] = np.nan
        products["trend"] = unknown
        actions.append({
            "dataset": "popularity",
            "action": "optional_enrichment_unavailable",
            "records_before": 0,
            "records_after": 0,
            "records_removed": 0,
        })
    products["trend"] = products["trend"].fillna(unknown).str.title()
    cleaned["products"] = products

    clickstream = cleaned["clickstream"]
    for column in ("user_id", "product_id"):
        clickstream[column] = pd.to_numeric(clickstream[column]).astype("int64")
    clickstream["event_type"] = clickstream["event_type"].str.strip()
    clickstream["timestamp"] = pd.to_datetime(
        clickstream["timestamp"], utc=True, errors="raise"
    )
    cleaned["clickstream"] = clickstream.sort_values(
        "timestamp", kind="stable"
    ).reset_index(drop=True)

    purchases = cleaned["purchasehistory"]
    for column in ("user_id", "product_id", "quantity"):
        purchases[column] = pd.to_numeric(purchases[column]).astype("int64")
    for column in ("amount", "rating"):
        purchases[column] = pd.to_numeric(purchases[column]).astype("float64")
    purchases["purchase_timestamp"] = pd.to_datetime(
        purchases["purchase_timestamp"], utc=True, errors="raise"
    )
    cleaned["purchasehistory"] = purchases.sort_values(
        "purchase_timestamp", kind="stable"
    ).reset_index(drop=True)
    return cleaned, actions


def build_interactions(
    clickstream: pd.DataFrame,
    purchases: pd.DataFrame,
    weights: dict[str, float],
    batch_id: str,
) -> pd.DataFrame:
    """Create event-level explicit and implicit feedback without collapsing."""
    clicks = pd.DataFrame({
        "interaction_id": clickstream["event_id"],
        "user_id": clickstream["user_id"],
        "product_id": clickstream["product_id"],
        "interaction_type": clickstream["event_type"],
        "explicit_rating": np.nan,
        "quantity": np.nan,
        "amount": np.nan,
        "event_timestamp": clickstream["timestamp"],
        "session_id": clickstream["session_id"],
        "source_dataset": "clickstream",
        "batch_id": batch_id,
    })
    orders = pd.DataFrame({
        "interaction_id": purchases["order_id"],
        "user_id": purchases["user_id"],
        "product_id": purchases["product_id"],
        "interaction_type": "Purchase",
        "explicit_rating": purchases["rating"],
        "quantity": purchases["quantity"],
        "amount": purchases["amount"],
        "event_timestamp": purchases["purchase_timestamp"],
        "session_id": pd.NA,
        "source_dataset": "purchasehistory",
        "batch_id": batch_id,
    })
    result = pd.concat([clicks, orders], ignore_index=True)
    result["interaction_weight"] = result["interaction_type"].map(weights)
    if result["interaction_weight"].isna().any():
        unknown = result.loc[result["interaction_weight"].isna(),
                             "interaction_type"].unique()
        raise DatasetPreparationError(f"Unweighted interaction types: {unknown}")
    result = derive_timestamp_features(result)
    return result.sort_values("event_timestamp", kind="stable").reset_index(
        drop=True
    )


def derive_timestamp_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Derive UTC calendar, recency, and cyclical interaction features."""
    result = frame.copy()
    timestamp = pd.to_datetime(result["event_timestamp"], utc=True)
    result["event_hour"] = timestamp.dt.hour.astype("int8")
    result["event_day_of_week"] = timestamp.dt.dayofweek.astype("int8")
    result["event_day"] = timestamp.dt.day.astype("int8")
    result["event_month"] = timestamp.dt.month.astype("int8")
    result["is_weekend"] = timestamp.dt.dayofweek.ge(5).astype("int8")
    latest = timestamp.max()
    result["days_since_latest_interaction"] = (
        latest - timestamp
    ).dt.total_seconds().div(86400)
    result["hour_sin"] = np.sin(2 * math.pi * result["event_hour"] / 24)
    result["hour_cos"] = np.cos(2 * math.pi * result["event_hour"] / 24)
    result["day_of_week_sin"] = np.sin(
        2 * math.pi * result["event_day_of_week"] / 7
    )
    result["day_of_week_cos"] = np.cos(
        2 * math.pi * result["event_day_of_week"] / 7
    )
    return result


def aggregate_interactions(interactions: pd.DataFrame) -> pd.DataFrame:
    """Aggregate event-level data while keeping explicit feedback separate."""
    work = interactions.copy()
    for label, target in (
        ("View", "view_count"),
        ("Wishlist", "wishlist_count"),
        ("AddToCart", "cart_count"),
        ("Purchase", "purchase_count"),
    ):
        work[target] = work["interaction_type"].eq(label).astype("int64")
    grouped = work.groupby(["user_id", "product_id"], as_index=False).agg(
        view_count=("view_count", "sum"),
        wishlist_count=("wishlist_count", "sum"),
        cart_count=("cart_count", "sum"),
        purchase_count=("purchase_count", "sum"),
        interaction_count=("interaction_id", "count"),
        total_quantity=("quantity", "sum"),
        total_spend=("amount", "sum"),
        latest_interaction_timestamp=("event_timestamp", "max"),
        explicit_rating=("explicit_rating", "max"),
        implicit_score=("interaction_weight", "sum"),
        batch_id=("batch_id", "first"),
    )
    return grouped


def encode_categoricals(
    users: pd.DataFrame,
    products: pd.DataFrame,
    config: PreparationConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Apply nominal one-hot and brand frequency encoding with metadata."""
    outputs = {"users": users.copy(), "products": products.copy()}
    metadata: dict[str, Any] = {"one_hot": {}, "frequency": {}}
    for dataset, columns in config.one_hot.items():
        frame = outputs[dataset]
        for column in columns:
            if column not in frame.columns:
                continue
            values = frame[column].fillna(config.unknown_category).astype("string")
            categories = sorted(set(values) | {config.unknown_category})
            for category in categories:
                safe = "".join(
                    char.lower() if char.isalnum() else "_"
                    for char in category
                ).strip("_") or "unknown"
                frame[f"{column}__{safe}"] = values.eq(category).astype("int8")
            metadata["one_hot"][f"{dataset}.{column}"] = {
                "categories": categories,
                "unknown": config.unknown_category,
                "method": "one_hot",
            }
        outputs[dataset] = frame
    for dataset, columns in config.frequency.items():
        frame = outputs[dataset]
        for column in columns:
            values = frame[column].fillna(config.unknown_category)
            frequencies = values.value_counts(normalize=True)
            frame[f"{column}_frequency"] = values.map(frequencies).astype(float)
            metadata["frequency"][f"{dataset}.{column}"] = {
                "method": "frequency",
                "frequencies": {
                    str(key): float(value)
                    for key, value in frequencies.items()
                },
                "unknown_value": 0.0,
            }
        outputs[dataset] = frame
    return outputs["users"], outputs["products"], metadata


def normalize_numericals(
    frames: dict[str, pd.DataFrame],
    config: PreparationConfig,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    """Fit deterministic standard scalers and retain transformation parameters."""
    outputs = {name: frame.copy() for name, frame in frames.items()}
    metadata: dict[str, Any] = {}
    for method, definitions in (
        ("standard", config.standard_scale),
        ("log1p_standard", config.log_scale),
    ):
        for dataset, columns in definitions.items():
            if dataset not in outputs:
                continue
            frame = outputs[dataset]
            for column in columns:
                if column not in frame.columns:
                    continue
                values = pd.to_numeric(frame[column], errors="coerce")
                valid = values.notna()
                target = values.copy()
                if method == "log1p_standard":
                    target = np.log1p(target.clip(lower=0))
                scaled = pd.Series(np.nan, index=frame.index, dtype=float)
                if valid.any():
                    scaler = StandardScaler()
                    scaled.loc[valid] = scaler.fit_transform(
                        target.loc[valid].to_numpy().reshape(-1, 1)
                    ).ravel()
                    metadata[f"{dataset}.{column}"] = {
                        "method": method,
                        "mean": float(scaler.mean_[0]),
                        "scale": float(scaler.scale_[0]),
                        "fitted_records": int(valid.sum()),
                    }
                frame[f"{column}_scaled"] = scaled
            outputs[dataset] = frame
    return outputs, metadata


def build_matrices(
    aggregated: pd.DataFrame,
    users: pd.DataFrame,
    products: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], sparse.csr_matrix]:
    """Build long-form matrix artifacts and a sparse in-memory implicit matrix."""
    user_ids = np.sort(users["user_id"].unique())
    product_ids = np.sort(products["product_id"].unique())
    user_index = {value: index for index, value in enumerate(user_ids)}
    item_index = {value: index for index, value in enumerate(product_ids)}
    observed = aggregated[
        aggregated["user_id"].isin(user_index)
        & aggregated["product_id"].isin(item_index)
    ].copy()
    rows = observed["user_id"].map(user_index).to_numpy()
    columns = observed["product_id"].map(item_index).to_numpy()
    matrix = sparse.csr_matrix(
        (observed["implicit_score"].to_numpy(), (rows, columns)),
        shape=(len(user_ids), len(product_ids)),
    )
    implicit_long = observed[
        ["user_id", "product_id", "implicit_score", "batch_id"]
    ].copy()
    ratings_long = observed.loc[
        observed["explicit_rating"].notna(),
        ["user_id", "product_id", "explicit_rating", "batch_id"],
    ].copy()
    possible = int(len(user_ids) * len(product_ids))
    pairs = int(len(observed))
    density = pairs / possible if possible else 0.0
    statistics = {
        "users": int(len(user_ids)),
        "products": int(len(product_ids)),
        "possible_user_product_pairs": possible,
        "observed_user_product_pairs": pairs,
        "density": density,
        "sparsity": 1.0 - density if possible else 1.0,
        "implicit_missing_value": 0,
        "explicit_missing_value": "NaN",
        "persistent_representation": "long_form_parquet",
        "in_memory_representation": "scipy_csr",
    }
    return implicit_long, ratings_long, statistics, matrix


def chronological_split(
    interactions: pd.DataFrame,
    config: PreparationConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Split globally by ordered timestamps to prevent future leakage."""
    if len(interactions) < config.minimum_records:
        raise DataSplitError("Too few interactions for a three-way split.")
    ordered = interactions.sort_values(
        ["event_timestamp", "interaction_id"], kind="stable"
    ).reset_index(drop=True)
    validation_size = max(1, int(len(ordered) * config.validation_ratio))
    test_size = max(1, int(len(ordered) * config.test_ratio))
    train_end = len(ordered) - validation_size - test_size
    validation_end = train_end + validation_size
    if train_end < 1:
        raise DataSplitError("Split ratios produced an empty partition.")
    train = ordered.iloc[:train_end].copy()
    validation = ordered.iloc[train_end:validation_end].copy()
    test = ordered.iloc[validation_end:].copy()
    metadata = {
        "strategy": "chronological",
        "train_records": len(train),
        "validation_records": len(validation),
        "test_records": len(test),
        "train_end": train["event_timestamp"].max().isoformat(),
        "validation_start": validation["event_timestamp"].min().isoformat(),
        "validation_end": validation["event_timestamp"].max().isoformat(),
        "test_start": test["event_timestamp"].min().isoformat(),
        "cold_start_validation_users": int(
            len(set(validation.user_id) - set(train.user_id))
        ),
        "cold_start_validation_products": int(
            len(set(validation.product_id) - set(train.product_id))
        ),
        "cold_start_test_users": int(len(set(test.user_id) - set(train.user_id))),
        "cold_start_test_products": int(
            len(set(test.product_id) - set(train.product_id))
        ),
    }
    return train, validation, test, metadata


def prepare_frames(
    frames: dict[str, pd.DataFrame],
    config: PreparationConfig,
    *,
    batch_id: str,
    reference_time: datetime,
) -> PreparedData:
    """Run the complete independently testable in-memory preparation pipeline."""
    cleaned, actions = clean_datasets(
        frames,
        batch_id=batch_id,
        reference_time=reference_time,
        unknown=config.unknown_category,
    )
    interactions = build_interactions(
        cleaned["clickstream"],
        cleaned["purchasehistory"],
        config.weights,
        batch_id,
    )
    aggregated = aggregate_interactions(interactions)
    users, products, encoders = encode_categoricals(
        cleaned["users"], cleaned["products"], config
    )
    normalized, scalers = normalize_numericals(
        {
            "users": users,
            "products": products,
            "interactions": interactions,
            "aggregated_interactions": aggregated,
        },
        config,
    )
    implicit, ratings, matrix_stats, _ = build_matrices(
        normalized["aggregated_interactions"],
        normalized["users"],
        normalized["products"],
    )
    train, validation, test, split = chronological_split(
        normalized["interactions"], config
    )
    return PreparedData(
        users=normalized["users"],
        products=normalized["products"],
        interactions=normalized["interactions"],
        aggregated=normalized["aggregated_interactions"],
        implicit_matrix=implicit,
        ratings_matrix=ratings,
        train=train,
        validation=validation,
        test=test,
        encoder_metadata=encoders,
        scaler_metadata=scalers,
        cleaning_actions=actions,
        split_metadata=split,
        matrix_statistics=matrix_stats,
    )

