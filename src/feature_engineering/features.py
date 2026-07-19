"""Leakage-safe recommendation feature computations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.neighbors import NearestNeighbors

from src.feature_engineering.config import FeatureConfig
from src.feature_engineering.errors import (
    FeatureComputationError,
    SimilarityComputationError,
)


@dataclass
class FeatureFrames:
    """All required feature groups plus calculation metadata."""

    users: pd.DataFrame
    items: pd.DataFrame
    user_items: pd.DataFrame
    cooccurrence: pd.DataFrame
    similarity: pd.DataFrame
    metadata: dict[str, Any]


def safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """Divide while retaining null for an undefined zero denominator."""
    return numerator.div(denominator.replace(0, np.nan))


def select_feature_events(
    prepared: dict[str, pd.DataFrame],
    split: str,
) -> tuple[pd.DataFrame, pd.Timestamp]:
    """Select configured events and cap them at the reference timestamp."""
    source = (
        prepared["train"] if split == "train"
        else prepared["interactions_prepared"]
    ).copy()
    if source.empty:
        raise FeatureComputationError("Feature source interactions are empty.")
    source["event_timestamp"] = pd.to_datetime(
        source["event_timestamp"], utc=True
    )
    reference = source["event_timestamp"].max()
    return source[source["event_timestamp"] <= reference].copy(), reference


def compute_user_features(
    events: pd.DataFrame,
    users: pd.DataFrame,
    products: pd.DataFrame,
    config: FeatureConfig,
    *,
    feature_batch_id: str,
    source_batch_id: str,
    reference: pd.Timestamp,
    created_at: str,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Create complete user behavior, rating, commerce, and affinity summaries."""
    event = _enrich(events, products)
    group = event.groupby("user_id")
    result = group.agg(
        total_interactions=("interaction_id", "count"),
        unique_products_interacted=("product_id", "nunique"),
        active_days=("event_timestamp", lambda x: x.dt.date.nunique()),
        session_count=("session_id", "nunique"),
        average_rating_given=("explicit_rating", "mean"),
        rating_count=("explicit_rating", "count"),
        rating_stddev=("explicit_rating", "std"),
        minimum_rating_given=("explicit_rating", "min"),
        maximum_rating_given=("explicit_rating", "max"),
        total_quantity_purchased=("quantity", "sum"),
        total_spend=("amount", "sum"),
        average_order_value=("amount", "mean"),
        maximum_order_value=("amount", "max"),
        last_interaction=("event_timestamp", "max"),
    ).reset_index()
    counts = _type_counts(event, "user_id")
    result = result.merge(counts, on="user_id", how="left")
    purchases = event[event.interaction_type.eq("Purchase")].groupby(
        "user_id"
    )["event_timestamp"].max().rename("last_purchase")
    result = result.merge(purchases, on="user_id", how="left")
    observation = (
        reference - event["event_timestamp"].min()
    ).total_seconds() / 86400
    result["interaction_frequency_per_day"] = (
        result["total_interactions"] / max(1.0, observation)
    )
    for days in (7, 30):
        count = event[
            event.event_timestamp >= reference - pd.Timedelta(days, unit="d")
        ].groupby("user_id").size()
        result[f"interaction_frequency_last_{days}d"] = (
            result["user_id"].map(count).fillna(0) / days
        )
    result["average_events_per_session"] = safe_ratio(
        result["total_interactions"], result["session_count"]
    )
    result["days_since_last_interaction"] = (
        reference - result["last_interaction"]
    ).dt.total_seconds() / 86400
    result["days_since_last_purchase"] = (
        reference - result["last_purchase"]
    ).dt.total_seconds() / 86400
    result = result.merge(
        users[["user_id", "registration_date"]], on="user_id", how="right"
    )
    result["user_tenure_days"] = (
        reference - pd.to_datetime(result["registration_date"], utc=True)
    ).dt.total_seconds().div(86400).clip(lower=0)
    result["preferred_category"] = result["user_id"].map(
        _preferred(event, "user_id", "category")
    )
    result["preferred_brand"] = result["user_id"].map(
        _preferred(event, "user_id", "brand")
    )
    result["preferred_interaction_type"] = result["user_id"].map(
        _preferred(event, "user_id", "interaction_type", weighted=False)
    )
    for column in (
        "total_interactions", "unique_products_interacted", "active_days",
        "session_count", "view_count", "wishlist_count",
        "add_to_cart_count", "purchase_count", "rating_count",
        "total_quantity_purchased", "total_spend",
    ):
        result[column] = result[column].fillna(0)
    result["view_to_cart_ratio"] = safe_ratio(
        result["add_to_cart_count"], result["view_count"]
    )
    result["cart_to_purchase_ratio"] = safe_ratio(
        result["purchase_count"], result["add_to_cart_count"]
    )
    result["purchase_conversion_rate"] = safe_ratio(
        result["purchase_count"], result["total_interactions"]
    )
    low = float(result.total_interactions.quantile(config.low_quantile))
    high = float(result.total_interactions.quantile(config.high_quantile))
    result["user_activity_level"] = np.select(
        [result.total_interactions < low, result.total_interactions > high],
        ["LOW", "HIGH"], default="MEDIUM",
    )
    result["cold_start_user_flag"] = (
        result.total_interactions < config.cold_user_minimum
    )
    return _lineage_columns(
        result.drop(columns=["last_interaction", "last_purchase",
                             "registration_date"]),
        feature_batch_id, source_batch_id, reference, created_at,
    ), {"low_threshold": low, "high_threshold": high}


def compute_item_features(
    events: pd.DataFrame,
    products: pd.DataFrame,
    config: FeatureConfig,
    *,
    feature_batch_id: str,
    source_batch_id: str,
    reference: pd.Timestamp,
    created_at: str,
) -> pd.DataFrame:
    """Create item activity, rating, commerce, catalog, and tail features."""
    group = events.groupby("product_id")
    result = group.agg(
        total_interactions=("interaction_id", "count"),
        unique_users=("user_id", "nunique"),
        average_rating=("explicit_rating", "mean"),
        rating_count=("explicit_rating", "count"),
        rating_stddev=("explicit_rating", "std"),
        minimum_rating=("explicit_rating", "min"),
        maximum_rating=("explicit_rating", "max"),
        total_quantity_sold=("quantity", "sum"),
        total_revenue=("amount", "sum"),
        average_selling_amount=("amount", "mean"),
    ).reset_index()
    result = result.merge(_type_counts(events, "product_id"),
                          on="product_id", how="left")
    result = products[[
        "product_id", "category", "brand", "price", "price_scaled",
        "product_age_days", "popularity_score",
    ]].merge(result, on="product_id", how="left")
    count_columns = [
        "total_interactions", "unique_users", "rating_count", "view_count",
        "wishlist_count", "add_to_cart_count", "purchase_count",
        "total_quantity_sold", "total_revenue",
    ]
    result[count_columns] = result[count_columns].fillna(0)
    maximum = max(1.0, float(result.total_interactions.max()))
    purchase_max = max(1.0, float(result.purchase_count.max()))
    result["interaction_popularity_score"] = (
        result.total_interactions / maximum * 100
    )
    result["purchase_popularity_score"] = (
        result.purchase_count / purchase_max * 100
    )
    result["external_popularity_score"] = result["popularity_score"]
    result["view_to_cart_ratio"] = safe_ratio(
        result.add_to_cart_count, result.view_count
    )
    result["cart_to_purchase_ratio"] = safe_ratio(
        result.purchase_count, result.add_to_cart_count
    )
    result["purchase_conversion_rate"] = safe_ratio(
        result.purchase_count, result.total_interactions
    )
    for days in (7, 30):
        counts = events[
            events.event_timestamp >= reference - pd.Timedelta(days, unit="d")
        ].groupby("product_id").size()
        result[f"interaction_count_last_{days}d"] = (
            result.product_id.map(counts).fillna(0)
        )
    previous = result["interaction_count_last_30d"] - (
        result["interaction_count_last_7d"]
    )
    result["popularity_growth_rate"] = safe_ratio(
        result["interaction_count_last_7d"], previous
    )
    result["item_popularity_rank"] = result.total_interactions.rank(
        method="dense", ascending=False
    ).astype(int)
    result["category_popularity_rank"] = result.groupby("category")[
        "total_interactions"
    ].rank(method="dense", ascending=False).astype(int)
    head_boundary = result.total_interactions.quantile(0.80)
    result["long_tail_flag"] = result.total_interactions < head_boundary
    result["cold_start_item_flag"] = (
        (result.unique_users < config.cold_item_users_minimum)
        | (result.total_interactions < config.cold_user_minimum)
    )
    return _lineage_columns(
        result.drop(columns=["popularity_score"]),
        feature_batch_id, source_batch_id, reference, created_at,
    )


def compute_user_item_features(
    events: pd.DataFrame,
    products: pd.DataFrame,
    *,
    feature_batch_id: str,
    source_batch_id: str,
    reference: pd.Timestamp,
    created_at: str,
) -> pd.DataFrame:
    """Create observed-pair behavioral, temporal, affinity, and price features."""
    event = _enrich(events, products)
    keys = ["user_id", "product_id"]
    group = event.groupby(keys)
    result = group.agg(
        interaction_count=("interaction_id", "count"),
        implicit_score=("interaction_weight", "sum"),
        average_explicit_rating=("explicit_rating", "mean"),
        latest_explicit_rating=("explicit_rating", "last"),
        total_quantity=("quantity", "sum"),
        total_spend=("amount", "sum"),
        first_interaction_timestamp=("event_timestamp", "min"),
        last_interaction_timestamp=("event_timestamp", "max"),
        session_count=("session_id", "nunique"),
    ).reset_index()
    result = result.merge(_type_counts(event, keys), on=keys, how="left")
    purchases = event[event.interaction_type.eq("Purchase")].groupby(keys)[
        "event_timestamp"
    ].agg(first_purchase_timestamp="min", last_purchase_timestamp="max")
    result = result.merge(purchases, on=keys, how="left")
    result["explicit_rating"] = result["latest_explicit_rating"]
    result["days_since_last_interaction"] = (
        reference - result.last_interaction_timestamp
    ).dt.total_seconds() / 86400
    result["days_since_last_purchase"] = (
        reference - result.last_purchase_timestamp
    ).dt.total_seconds() / 86400
    intervals = event.sort_values("event_timestamp").groupby(keys)[
        "event_timestamp"
    ].diff().dt.total_seconds().div(3600).groupby(
        [event.user_id, event.product_id]
    ).mean()
    result["average_time_between_interactions_hours"] = pd.MultiIndex.from_frame(
        result[keys]
    ).map(intervals)
    result["user_item_view_to_cart_ratio"] = safe_ratio(
        result.add_to_cart_count, result.view_count
    )
    result["user_item_cart_to_purchase_ratio"] = safe_ratio(
        result.purchase_count, result.add_to_cart_count
    )
    user_weight = event.groupby("user_id").interaction_weight.sum()
    category_weight = event.groupby(
        ["user_id", "category"]
    ).interaction_weight.sum()
    brand_weight = event.groupby(
        ["user_id", "brand"]
    ).interaction_weight.sum()
    result = result.merge(
        products[["product_id", "category", "brand", "price"]],
        on="product_id", how="left",
    )
    result["user_category_affinity"] = [
        category_weight.get((u, c), 0) / user_weight.get(u, 1)
        for u, c in zip(result.user_id, result.category)
    ]
    result["user_brand_affinity"] = [
        brand_weight.get((u, b), 0) / user_weight.get(u, 1)
        for u, b in zip(result.user_id, result.brand)
    ]
    weighted_price = event["price"] * event["interaction_weight"]
    preferred_price = weighted_price.groupby(event["user_id"]).sum().div(
        event["interaction_weight"].groupby(event["user_id"]).sum()
    )
    result["price_preference_distance"] = (
        result.price - result.user_id.map(preferred_price)
    ).abs()
    result["price_preference_similarity"] = 1 / (
        1 + result.price_preference_distance
    )
    return _lineage_columns(
        result.drop(columns=["category", "brand", "price"]),
        feature_batch_id, source_batch_id, reference, created_at,
    )


def compute_pair_features(
    events: pd.DataFrame,
    products: pd.DataFrame,
    config: FeatureConfig,
    *,
    feature_batch_id: str,
    source_batch_id: str,
    reference: pd.Timestamp,
    created_at: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute filtered sparse co-occurrence and top-K item similarities."""
    users = np.sort(events.user_id.unique())
    items = np.sort(events.product_id.unique())
    user_index = {value: index for index, value in enumerate(users)}
    item_index = {value: index for index, value in enumerate(items)}
    pairs = events[["user_id", "product_id"]].drop_duplicates()
    binary = sparse.csr_matrix(
        (
            np.ones(len(pairs)),
            (
                pairs.user_id.map(user_index).to_numpy(),
                pairs.product_id.map(item_index).to_numpy(),
            ),
        ),
        shape=(len(users), len(items)),
    )
    counts = (binary.T @ binary).tocoo()
    user_counts = np.asarray(binary.sum(axis=0)).ravel()
    mask = (
        (counts.row < counts.col)
        & (counts.data >= config.minimum_cooccurrence)
        & (counts.data / len(users) >= config.minimum_support)
    )
    a_index, b_index, common = (
        counts.row[mask], counts.col[mask], counts.data[mask]
    )
    cooc = pd.DataFrame({
        "item_id_a": items[a_index],
        "item_id_b": items[b_index],
        "cooccurrence_count": common.astype(int),
        "cooccurring_user_count": common.astype(int),
        "item_a_user_count": user_counts[a_index].astype(int),
        "item_b_user_count": user_counts[b_index].astype(int),
    })
    session_pairs = _pair_counts(events.dropna(subset=["session_id"]),
                                 "session_id")
    purchase_pairs = _pair_counts(
        events[events.interaction_type.eq("Purchase")], "user_id"
    )
    cooc["cooccurring_session_count"] = [
        session_pairs.get((a, b), 0)
        for a, b in zip(cooc.item_id_a, cooc.item_id_b)
    ]
    cooc["co_purchase_count"] = [
        purchase_pairs.get((a, b), 0)
        for a, b in zip(cooc.item_id_a, cooc.item_id_b)
    ]
    cooc["support"] = cooc.cooccurrence_count / len(users)
    cooc["confidence_a_to_b"] = (
        cooc.cooccurrence_count / cooc.item_a_user_count
    )
    cooc["confidence_b_to_a"] = (
        cooc.cooccurrence_count / cooc.item_b_user_count
    )
    cooc["lift"] = cooc.support / (
        (cooc.item_a_user_count / len(users))
        * (cooc.item_b_user_count / len(users))
    )
    cooc = _limit_pair_neighbors(cooc, config.maximum_neighbors)
    cooc = _lineage_columns(
        cooc, feature_batch_id, source_batch_id, reference, created_at
    )
    try:
        weighted = events.groupby(["user_id", "product_id"])[
            "interaction_weight"
        ].sum().reset_index()
        matrix = sparse.csr_matrix(
            (
                weighted.interaction_weight,
                (
                    weighted.product_id.map(item_index),
                    weighted.user_id.map(user_index),
                ),
            ),
            shape=(len(items), len(users)),
        )
        neighbors = NearestNeighbors(
            metric="cosine", algorithm="brute",
            n_neighbors=min(config.top_k + 1, len(items)),
        ).fit(matrix)
        distances, indices = neighbors.kneighbors(matrix)
    except (ValueError, TypeError) as exc:
        raise SimilarityComputationError(
            "Unable to calculate sparse item similarities."
        ) from exc
    cooc_lookup = {
        (int(row.item_id_a), int(row.item_id_b)): row
        for row in cooc.itertuples()
    }
    catalog = products.set_index("product_id")
    rows: list[dict[str, Any]] = []
    for item_position, item_id in enumerate(items):
        candidates: list[dict[str, Any]] = []
        for distance, other_position in zip(
            distances[item_position], indices[item_position]
        ):
            other_id = int(items[other_position])
            if int(item_id) == other_id:
                continue
            key = tuple(sorted((int(item_id), other_id)))
            pair = cooc_lookup.get(key)
            intersection = pair.cooccurrence_count if pair else 0
            union = (
                user_counts[item_position] + user_counts[other_position]
                - intersection
            )
            left, right = catalog.loc[item_id], catalog.loc[other_id]
            metrics = {
                "cosine_similarity": 1 - float(distance),
                "jaccard_similarity": intersection / union if union else 0,
                "category_similarity": float(left.category == right.category),
                "brand_similarity": float(left.brand == right.brand),
                "price_similarity": 1 / (
                    1 + abs(left.price - right.price)
                    / max(1.0, float(products.price.std()))
                ),
                "rating_similarity": 1 / (
                    1 + abs(left.average_rating - right.average_rating)
                ),
            }
            score = sum(
                metrics[f"{name}_similarity"] * weight
                for name, weight in config.similarity_weights.items()
            )
            if score >= config.minimum_similarity:
                candidates.append({
                    "product_id": int(item_id),
                    "similar_product_id": other_id,
                    **metrics,
                    "combined_similarity_score": score,
                })
        candidates.sort(
            key=lambda value: value["combined_similarity_score"],
            reverse=True,
        )
        for rank, candidate in enumerate(candidates[:config.top_k], 1):
            candidate["similarity_rank"] = rank
            rows.append(candidate)
    similarity = _lineage_columns(
        pd.DataFrame(rows), feature_batch_id, source_batch_id,
        reference, created_at,
    )
    return cooc, similarity


def compute_all_features(
    prepared: dict[str, pd.DataFrame],
    config: FeatureConfig,
    *,
    feature_batch_id: str,
    source_batch_id: str,
    created_at: str,
) -> FeatureFrames:
    """Create every required feature group from the configured source split."""
    events, reference = select_feature_events(prepared, config.source_split)
    products = prepared["products_prepared"]
    users, thresholds = compute_user_features(
        events, prepared["users_prepared"], products, config,
        feature_batch_id=feature_batch_id, source_batch_id=source_batch_id,
        reference=reference, created_at=created_at,
    )
    items = compute_item_features(
        events, products, config, feature_batch_id=feature_batch_id,
        source_batch_id=source_batch_id, reference=reference,
        created_at=created_at,
    )
    user_items = compute_user_item_features(
        events, products, feature_batch_id=feature_batch_id,
        source_batch_id=source_batch_id, reference=reference,
        created_at=created_at,
    )
    cooc, similarity = compute_pair_features(
        events, products, config, feature_batch_id=feature_batch_id,
        source_batch_id=source_batch_id, reference=reference,
        created_at=created_at,
    )
    return FeatureFrames(users, items, user_items, cooc, similarity, {
        "feature_reference_timestamp": reference.isoformat(),
        "source_split": config.source_split,
        "activity_thresholds": thresholds,
        "source_event_count": len(events),
    })


def _type_counts(events: pd.DataFrame, keys: str | list[str]) -> pd.DataFrame:
    keys_list = [keys] if isinstance(keys, str) else keys
    counts = events.pivot_table(
        index=keys_list, columns="interaction_type",
        values="interaction_id", aggfunc="count", fill_value=0,
    ).reset_index()
    return counts.rename(columns={
        "View": "view_count", "Wishlist": "wishlist_count",
        "AddToCart": "add_to_cart_count", "Purchase": "purchase_count",
    }).reindex(columns=keys_list + [
        "view_count", "wishlist_count", "add_to_cart_count", "purchase_count"
    ], fill_value=0)


def _enrich(events: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    return events.merge(
        products[["product_id", "category", "brand", "price"]],
        on="product_id", how="left",
    )


def _preferred(
    frame: pd.DataFrame, key: str, value: str, weighted: bool = True
) -> pd.Series:
    weights = "interaction_weight" if weighted else "interaction_id"
    grouped = frame.groupby([key, value])[weights].agg(
        "sum" if weighted else "count"
    ).reset_index(name="score")
    return grouped.sort_values(
        [key, "score", value], ascending=[True, False, True]
    ).drop_duplicates(key).set_index(key)[value]


def _lineage_columns(
    frame: pd.DataFrame, feature_batch_id: str, source_batch_id: str,
    reference: pd.Timestamp, created_at: str,
) -> pd.DataFrame:
    result = frame.copy()
    result.insert(0, "feature_batch_id", feature_batch_id)
    result.insert(1, "source_batch_id", source_batch_id)
    result.insert(2, "feature_reference_timestamp", reference.isoformat())
    result["created_at"] = created_at
    return result


def _pair_counts(events: pd.DataFrame, group_column: str) -> dict[tuple[int, int], int]:
    if events.empty:
        return {}
    binary = pd.crosstab(events[group_column], events.product_id).clip(upper=1)
    matrix = sparse.csr_matrix(binary.to_numpy())
    cooc = (matrix.T @ matrix).tocoo()
    items = binary.columns.to_numpy()
    return {
        (int(items[a]), int(items[b])): int(count)
        for a, b, count in zip(cooc.row, cooc.col, cooc.data) if a < b
    }


def _limit_pair_neighbors(frame: pd.DataFrame, maximum: int) -> pd.DataFrame:
    if frame.empty:
        return frame
    ranked_a = frame.sort_values(
        ["item_id_a", "cooccurrence_count"], ascending=[True, False]
    ).groupby("item_id_a").head(maximum)
    ranked_b = frame.sort_values(
        ["item_id_b", "cooccurrence_count"], ascending=[True, False]
    ).groupby("item_id_b").head(maximum)
    return pd.concat([ranked_a, ranked_b]).drop_duplicates(
        ["item_id_a", "item_id_b"]
    ).reset_index(drop=True)
