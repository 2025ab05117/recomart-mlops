"""Feature-store-backed cosine content recommender."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder, StandardScaler, normalize

from src.modeling.errors import TrainingError


@dataclass
class ContentBasedRecommender:
    """Cosine content recommender over category, brand, price, and rating."""

    top_k: int = 20

    def fit(self, items: pd.DataFrame) -> "ContentBasedRecommender":
        """Fit a sparse content vector matrix from feature-store item rows."""
        required = {"product_id", "category", "brand", "price", "average_rating"}
        if not required.issubset(items.columns):
            raise TrainingError("Content item features are incomplete.")
        self.items = items.drop_duplicates("product_id").reset_index(drop=True)
        self.product_index = {
            value: index for index, value in enumerate(self.items.product_id)
        }
        self.transformer = ColumnTransformer([
            ("categorical", OneHotEncoder(handle_unknown="ignore"),
             ["category", "brand"]),
            ("numeric", StandardScaler(), ["price", "average_rating"]),
        ])
        clean = self.items.copy()
        clean["average_rating"] = clean.average_rating.fillna(
            clean.average_rating.mean()
        )
        self.matrix = normalize(self.transformer.fit_transform(clean))
        category_count = len(
            self.transformer.named_transformers_["categorical"].categories_[0]
        )
        brand_count = len(
            self.transformer.named_transformers_["categorical"].categories_[1]
        )
        total = self.matrix.shape[1]
        self.feature_importance = {
            "category": category_count / total,
            "brand": brand_count / total,
            "price": 1 / total,
            "average_rating": 1 / total,
        }
        return self

    def similar_items(
        self, product_id: int, top_k: int | None = None
    ) -> pd.DataFrame:
        """Return top cosine-similar products, excluding the query product."""
        if product_id not in self.product_index:
            raise TrainingError(f"Unknown product_id: {product_id}")
        index = self.product_index[product_id]
        score_matrix = self.matrix[index] @ self.matrix.T
        scores = (
            score_matrix.toarray().ravel()
            if hasattr(score_matrix, "toarray")
            else np.asarray(score_matrix).ravel()
        )
        order = np.argsort(-scores)
        limit = top_k or self.top_k
        rows = []
        for other in order:
            candidate = int(self.items.iloc[other].product_id)
            if candidate == product_id:
                continue
            rows.append({"product_id": candidate, "score": float(scores[other])})
            if len(rows) == limit:
                break
        for rank, row in enumerate(rows, 1):
            row["rank"] = rank
        return pd.DataFrame(rows)

    def recommend_for_user(
        self, history: pd.DataFrame, user_id: int, top_k: int
    ) -> pd.DataFrame:
        """Recommend by maximum similarity to a user's observed products."""
        seen = set(history.loc[history.user_id == user_id, "product_id"])
        if not seen:
            return pd.DataFrame(columns=["product_id", "score", "rank"])
        valid = [self.product_index[item] for item in seen
                 if item in self.product_index]
        if not valid:
            return pd.DataFrame(columns=["product_id", "score", "rank"])
        profile_raw = self.matrix[valid].mean(axis=0)
        if hasattr(profile_raw, "A"):
            profile_raw = profile_raw.A
        profile = normalize(np.asarray(profile_raw).reshape(1, -1))
        score_matrix = profile @ self.matrix.T
        scores = (
            score_matrix.toarray().ravel()
            if hasattr(score_matrix, "toarray")
            else np.asarray(score_matrix).ravel()
        )
        order = np.argsort(-scores)
        rows = []
        for index in order:
            item = int(self.items.iloc[index].product_id)
            if item in seen:
                continue
            rows.append({"product_id": item, "score": float(scores[index])})
            if len(rows) == top_k:
                break
        for rank, row in enumerate(rows, 1):
            row["rank"] = rank
        return pd.DataFrame(rows)




