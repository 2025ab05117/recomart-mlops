"""Deterministic explicit-feedback Funk SVD collaborative recommender."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.modeling.errors import TrainingError


@dataclass
class FunkSVDRecommender:
    """Biased matrix factorization trained using stochastic gradient descent."""

    factors: int
    learning_rate: float
    regularization: float
    epochs: int
    random_seed: int
    rating_min: float = 1.0
    rating_max: float = 5.0

    def fit(self, ratings: pd.DataFrame) -> "FunkSVDRecommender":
        """Fit user/item factors from user_id, product_id, explicit_rating."""
        data = ratings.dropna(subset=["explicit_rating"]).copy()
        if data.empty:
            raise TrainingError("Collaborative training has no explicit ratings.")
        self.user_ids = np.sort(data.user_id.unique())
        self.item_ids = np.sort(data.product_id.unique())
        self.user_index = {value: index for index, value in enumerate(self.user_ids)}
        self.item_index = {value: index for index, value in enumerate(self.item_ids)}
        rng = np.random.default_rng(self.random_seed)
        self.global_mean = float(data.explicit_rating.mean())
        self.user_bias = np.zeros(len(self.user_ids))
        self.item_bias = np.zeros(len(self.item_ids))
        self.user_factors = rng.normal(0, 0.1, (len(self.user_ids), self.factors))
        self.item_factors = rng.normal(0, 0.1, (len(self.item_ids), self.factors))
        triples = [
            (self.user_index[u], self.item_index[i], float(r))
            for u, i, r in data[
                ["user_id", "product_id", "explicit_rating"]
            ].itertuples(index=False, name=None)
        ]
        for _ in range(self.epochs):
            rng.shuffle(triples)
            for user, item, rating in triples:
                prediction = self._raw(user, item)
                error = rating - prediction
                old_user = self.user_factors[user].copy()
                self.user_bias[user] += self.learning_rate * (
                    error - self.regularization * self.user_bias[user]
                )
                self.item_bias[item] += self.learning_rate * (
                    error - self.regularization * self.item_bias[item]
                )
                self.user_factors[user] += self.learning_rate * (
                    error * self.item_factors[item]
                    - self.regularization * self.user_factors[user]
                )
                self.item_factors[item] += self.learning_rate * (
                    error * old_user
                    - self.regularization * self.item_factors[item]
                )
        self.seen = data.groupby("user_id").product_id.apply(set).to_dict()
        return self

    def predict(self, user_id: int, product_id: int) -> float:
        """Predict a clipped explicit rating with cold-start fallbacks."""
        user = self.user_index.get(user_id)
        item = self.item_index.get(product_id)
        if user is None and item is None:
            score = self.global_mean
        elif user is None:
            score = self.global_mean + self.item_bias[item]
        elif item is None:
            score = self.global_mean + self.user_bias[user]
        else:
            score = self._raw(user, item)
        return float(np.clip(score, self.rating_min, self.rating_max))

    def recommend(self, user_id: int, top_k: int = 10) -> pd.DataFrame:
        """Return top unseen product IDs with predicted scores and ranks."""
        seen = self.seen.get(user_id, set())
        candidates = [
            (int(item), self.predict(user_id, int(item)))
            for item in self.item_ids if item not in seen
        ]
        candidates.sort(key=lambda value: (-value[1], value[0]))
        return pd.DataFrame([
            {"product_id": item, "score": score, "rank": rank}
            for rank, (item, score) in enumerate(candidates[:top_k], 1)
        ])

    def _raw(self, user: int, item: int) -> float:
        return float(
            self.global_mean + self.user_bias[user] + self.item_bias[item]
            + np.dot(self.user_factors[user], self.item_factors[item])
        )
