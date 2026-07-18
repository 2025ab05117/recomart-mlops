"""Explicit-rating and top-K recommendation evaluation metrics."""

from __future__ import annotations

import math
import time
from typing import Callable

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

from src.modeling.errors import EvaluationError

RecommendFunction = Callable[[int, int], pd.DataFrame]


def rating_metrics(
    predict: Callable[[int, int], float], test: pd.DataFrame
) -> dict[str, float]:
    """Calculate RMSE and MAE on non-null explicit ratings."""
    ratings = test.dropna(subset=["explicit_rating"])
    if ratings.empty:
        return {"rmse": float("nan"), "mae": float("nan")}
    actual = ratings.explicit_rating.to_numpy()
    predicted = np.array([
        predict(int(user), int(item))
        for user, item in ratings[["user_id", "product_id"]].itertuples(
            index=False, name=None
        )
    ])
    return {
        "rmse": float(math.sqrt(mean_squared_error(actual, predicted))),
        "mae": float(mean_absolute_error(actual, predicted)),
    }


def ranking_metrics(
    recommend: RecommendFunction,
    evaluation: pd.DataFrame,
    train: pd.DataFrame,
    *,
    top_k: int,
    threshold: float,
    catalog: set[int],
    similarity: pd.DataFrame | None = None,
) -> dict[str, float]:
    """Calculate ranking, coverage, diversity, novelty, and inference metrics."""
    relevant = evaluation[
        evaluation.explicit_rating.fillna(0) >= threshold
    ].groupby("user_id").product_id.apply(set)
    if relevant.empty:
        raise EvaluationError("Evaluation split has no relevant items.")
    popularity = train.groupby("product_id").user_id.nunique()
    total_users = max(1, train.user_id.nunique())
    recommended_catalog: set[int] = set()
    precision, recall, average_precision, ndcg, hits = [], [], [], [], []
    novelty, diversity = [], []
    similarity_lookup = {}
    if similarity is not None and not similarity.empty:
        similarity_lookup = {
            (int(row.product_id), int(row.similar_product_id)):
            float(row.combined_similarity_score)
            for row in similarity.itertuples()
        }
    inference_started = time.perf_counter()
    for user_id, truth in relevant.items():
        recommendations = recommend(int(user_id), top_k)
        items = [int(value) for value in recommendations.product_id]
        recommended_catalog.update(items)
        flags = [item in truth for item in items]
        hit_count = sum(flags)
        precision.append(hit_count / top_k)
        recall.append(hit_count / len(truth))
        hits.append(float(hit_count > 0))
        precisions = [
            sum(flags[:index]) / index
            for index in range(1, len(flags) + 1) if flags[index - 1]
        ]
        average_precision.append(
            sum(precisions) / min(len(truth), top_k) if precisions else 0
        )
        dcg = sum(
            int(flag) / math.log2(index + 2)
            for index, flag in enumerate(flags)
        )
        ideal = sum(
            1 / math.log2(index + 2)
            for index in range(min(len(truth), top_k))
        )
        ndcg.append(dcg / ideal if ideal else 0)
        novelty.extend([
            -math.log2(max(1, popularity.get(item, 0)) / total_users)
            for item in items
        ])
        pair_distances = []
        for left_index, left in enumerate(items):
            for right in items[left_index + 1:]:
                similarity_value = similarity_lookup.get(
                    (left, right),
                    similarity_lookup.get((right, left), 0.0),
                )
                pair_distances.append(1 - similarity_value)
        if pair_distances:
            diversity.append(float(np.mean(pair_distances)))
    elapsed = time.perf_counter() - inference_started
    return {
        f"precision_at_{top_k}": float(np.mean(precision)),
        f"recall_at_{top_k}": float(np.mean(recall)),
        f"map_at_{top_k}": float(np.mean(average_precision)),
        f"ndcg_at_{top_k}": float(np.mean(ndcg)),
        f"hit_rate_at_{top_k}": float(np.mean(hits)),
        "coverage": len(recommended_catalog) / max(1, len(catalog)),
        "catalog_coverage": len(recommended_catalog) / max(1, len(catalog)),
        "diversity": float(np.mean(diversity)) if diversity else 0.0,
        "intra_list_diversity": (
            float(np.mean(diversity)) if diversity else 0.0
        ),
        "novelty": float(np.mean(novelty)) if novelty else 0.0,
        "inference_time_seconds": elapsed,
        "evaluated_users": float(len(relevant)),
    }
