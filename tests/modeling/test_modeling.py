"""Focused unit tests for RecoMart model training and evaluation."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from src.modeling.collaborative import FunkSVDRecommender
from src.modeling.content_based import ContentBasedRecommender
from src.modeling.evaluation import ranking_metrics, rating_metrics
from src.modeling.persistence import save_model_bundle


def interactions() -> pd.DataFrame:
    """Return deterministic explicit-feedback fixtures."""
    rows = [
        (1, 10, 5.0), (1, 11, 4.0), (1, 12, 3.0),
        (2, 10, 4.0), (2, 12, 5.0), (2, 13, 4.0),
        (3, 11, 5.0), (3, 12, 4.0), (3, 13, 5.0),
    ]
    return pd.DataFrame(rows, columns=["user_id", "product_id",
                                       "explicit_rating"])


def items() -> pd.DataFrame:
    """Return deterministic catalog fixtures."""
    return pd.DataFrame({
        "product_id": [10, 11, 12, 13, 14],
        "category": ["Drama", "Drama", "Comedy", "Comedy", "Drama"],
        "brand": ["A", "A", "B", "B", "C"],
        "price": [100.0, 110.0, 200.0, 210.0, 105.0],
        "average_rating": [4.5, 4.2, 4.0, 4.7, 3.9],
    })


def test_collaborative_training_is_deterministic_and_recommends_unseen() -> None:
    """Funk SVD should fit explicit ratings and exclude observed items."""
    first = FunkSVDRecommender(factors=4, learning_rate=0.01, regularization=0.02, epochs=4, random_seed=7)
    second = FunkSVDRecommender(factors=4, learning_rate=0.01, regularization=0.02, epochs=4, random_seed=7)
    first.fit(interactions())
    second.fit(interactions())
    assert first.predict(1, 10) == second.predict(1, 10)
    recommendations = first.recommend(1, top_k=2)
    assert list(recommendations.columns) == ["product_id", "score", "rank"]
    assert set(recommendations.product_id).isdisjoint({10, 11, 12})


def test_collaborative_rating_metrics_are_finite() -> None:
    """Rating evaluation should return finite RMSE and MAE."""
    model = FunkSVDRecommender(factors=3, learning_rate=0.01, regularization=0.02, epochs=3, random_seed=3)
    model.fit(interactions())
    metrics = rating_metrics(model.predict, interactions())
    assert np.isfinite(metrics["rmse"])
    assert np.isfinite(metrics["mae"])


def test_content_training_similarity_and_user_recommendation() -> None:
    """Content model should exclude self and previously seen products."""
    model = ContentBasedRecommender(top_k=3).fit(items())
    similar = model.similar_items(10, 3)
    assert len(similar) == 3
    assert 10 not in set(similar.product_id)
    recommended = model.recommend_for_user(interactions(), 1, 2)
    assert len(recommended) == 2
    assert set(recommended.product_id).isdisjoint({10, 11, 12})
    assert abs(sum(model.feature_importance.values()) - 1.0) < 1e-12


def test_ranking_metrics() -> None:
    """Top-K evaluator should calculate bounded relevance and coverage."""
    evaluation = pd.DataFrame({
        "user_id": [1, 2],
        "product_id": [13, 11],
        "explicit_rating": [5.0, 4.0],
    })

    def recommend(user_id: int, top_k: int) -> pd.DataFrame:
        values = [13, 14] if user_id == 1 else [11, 14]
        return pd.DataFrame({
            "product_id": values[:top_k],
            "score": [1.0, 0.5][:top_k],
            "rank": range(1, min(top_k, 2) + 1),
        })

    metrics = ranking_metrics(
        recommend, evaluation, interactions(), top_k=2, threshold=4,
        catalog={10, 11, 12, 13, 14},
    )
    assert metrics["precision_at_2"] == 0.5
    assert metrics["recall_at_2"] == 1.0
    assert metrics["hit_rate_at_2"] == 1.0
    assert 0 < metrics["coverage"] <= 1


def test_model_bundle_persistence(tmp_path) -> None:
    """Model, metadata, and effective configuration should persist together."""
    model = FunkSVDRecommender(factors=2, learning_rate=0.01, regularization=0.02, epochs=1, random_seed=1).fit(interactions())
    paths = save_model_bundle(
        model, tmp_path / "bundle",
        metadata={"model_run_id": "MODEL_TEST", "status": "SUCCESS"},
        configuration={"collaborative": {"factors": 2}},
    )
    assert all(path.exists() for path in paths)
    metadata = json.loads(paths[1].read_text(encoding="utf-8"))
    assert metadata["model_run_id"] == "MODEL_TEST"

