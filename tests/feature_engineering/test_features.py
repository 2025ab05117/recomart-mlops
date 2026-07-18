"""Focused feature computation and SQLite integration tests."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine, inspect, text

from src.feature_engineering.config import load_feature_config
from src.feature_engineering.features import (
    compute_all_features,
    safe_ratio,
    select_feature_events,
)
from src.feature_engineering.loader import resolve_prepared_batch
from src.feature_engineering.runner import FeatureRunner

NOW = datetime(2026, 7, 19, 12, tzinfo=timezone.utc)


@pytest.fixture
def prepared() -> dict[str, pd.DataFrame]:
    """Return deterministic prepared tables with ratings and sparse pairs."""
    users = pd.DataFrame([
        {"user_id": 1, "registration_date": pd.Timestamp("2025-01-01", tz="UTC")},
        {"user_id": 2, "registration_date": pd.Timestamp("2025-06-01", tz="UTC")},
        {"user_id": 3, "registration_date": pd.Timestamp("2026-01-01", tz="UTC")},
    ])
    products = pd.DataFrame([
        {"product_id": 10, "category": "Drama", "brand": "A",
         "price": 100.0, "price_scaled": -1.0, "product_age_days": 1000.0,
         "popularity_score": 80.0, "average_rating": 4.5},
        {"product_id": 20, "category": "Drama", "brand": "B",
         "price": 120.0, "price_scaled": 0.0, "product_age_days": 900.0,
         "popularity_score": 70.0, "average_rating": 4.0},
        {"product_id": 30, "category": "Comedy", "brand": "A",
         "price": 300.0, "price_scaled": 1.0, "product_age_days": 800.0,
         "popularity_score": np.nan, "average_rating": 3.0},
    ])
    rows = []
    spec = [
        (1, 10, "View", None, "2026-07-10T09:00:00Z"),
        (1, 20, "AddToCart", None, "2026-07-18T09:00:00Z"),
        (1, 20, "Purchase", 5.0, "2026-07-18T10:00:00Z"),
        (2, 10, "View", None, "2026-07-18T11:00:00Z"),
        (2, 20, "Purchase", 4.0, "2026-07-19T09:00:00Z"),
        (3, 30, "View", None, "2026-07-19T10:00:00Z"),
    ]
    weights = {"View": 1.0, "AddToCart": 3.0, "Purchase": 5.0}
    for user, product, kind, rating, timestamp in spec:
        rows.append({
            "interaction_id": str(uuid.uuid4()), "user_id": user,
            "product_id": product, "interaction_type": kind,
            "explicit_rating": rating,
            "quantity": 1.0 if kind == "Purchase" else np.nan,
            "amount": 120.0 if kind == "Purchase" else np.nan,
            "event_timestamp": pd.Timestamp(timestamp),
            "session_id": str(uuid.uuid4()), "interaction_weight": weights[kind],
        })
    interactions = pd.DataFrame(rows)
    return {
        "users_prepared": users,
        "products_prepared": products,
        "interactions_prepared": interactions,
        "train": interactions.iloc[:4].copy(),
        "validation": interactions.iloc[4:5].copy(),
        "test": interactions.iloc[5:].copy(),
    }


def _config(tmp_path: Path | None = None, source: str = "train"):
    overrides = {"source_split": source}
    if tmp_path:
        overrides.update({
            "prepared_path": tmp_path / "prepared",
            "output_path": tmp_path / "features",
            "database_url": f"sqlite:///{tmp_path / 'features.db'}",
        })
    return load_feature_config(overrides=overrides)


def test_safe_ratio_retains_undefined_null() -> None:
    result = safe_ratio(pd.Series([2, 1]), pd.Series([4, 0]))
    assert result.iloc[0] == 0.5
    assert pd.isna(result.iloc[1])


def test_train_reference_prevents_validation_test_leakage(prepared) -> None:
    events, reference = select_feature_events(prepared, "train")
    assert len(events) == 4
    assert reference == prepared["train"].event_timestamp.max()
    assert reference < prepared["validation"].event_timestamp.min()


def test_user_item_and_similarity_features(tmp_path: Path, prepared) -> None:
    frames = compute_all_features(
        prepared, _config(source="all"), feature_batch_id="F",
        source_batch_id="B", created_at="2026-07-19T12:00:00Z",
    )
    user1 = frames.users.set_index("user_id").loc[1]
    assert user1.total_interactions == 3
    assert user1.average_rating_given == 5
    assert user1.interaction_frequency_last_7d > 0
    assert frames.users.user_activity_level.isin(["LOW", "MEDIUM", "HIGH"]).all()
    assert frames.users.cold_start_user_flag.all()
    item20 = frames.items.set_index("product_id").loc[20]
    assert item20.average_rating == 4.5
    assert pd.isna(frames.items.set_index("product_id").loc[30].average_rating)
    pair = frames.user_items.set_index(["user_id", "product_id"]).loc[(1, 20)]
    assert 0 <= pair.user_category_affinity <= 1
    assert 0 <= pair.user_brand_affinity <= 1
    assert pair.price_preference_distance >= 0
    assert (frames.cooccurrence.item_id_a < frames.cooccurrence.item_id_b).all()
    assert frames.cooccurrence.support.between(0, 1).all()
    assert frames.cooccurrence.confidence_a_to_b.between(0, 1).all()
    assert (frames.similarity.product_id !=
            frames.similarity.similar_product_id).all()
    assert frames.similarity.groupby("product_id").size().max() <= 50
    assert frames.similarity.combined_similarity_score.between(0, 1).all()


def _prepared_manifest(tmp_path: Path, prepared) -> str:
    batch_id = "RECO_TEST"
    output = tmp_path / "prepared" / "batch"
    output.mkdir(parents=True)
    paths = {}
    tables = dict(prepared)
    tables["user_product_interactions"] = pd.DataFrame(
        {"user_id": [1], "product_id": [10]}
    )
    for name in (
        "users_prepared", "products_prepared", "interactions_prepared",
        "user_product_interactions", "train", "validation", "test",
    ):
        path = output / f"{name}.parquet"
        tables[name].to_parquet(path, index=False)
        paths[name] = str(path)
    manifest = {
        "batch_id": batch_id, "preparation_run_id": str(uuid.uuid4()),
        "correlation_id": str(uuid.uuid4()),
        "started_at": "2026-07-19T12:00:00Z", "status": "SUCCESS",
        "output_dataset_paths": paths,
    }
    (output / "preparation_manifest.json").write_text(json.dumps(manifest))
    return batch_id


def test_sqlite_runner_storage_lineage_snapshots_and_idempotency(
    tmp_path: Path, prepared
) -> None:
    batch_id = _prepared_manifest(tmp_path, prepared)
    config = _config(tmp_path, source="train")
    runner = FeatureRunner(config, utc_clock=lambda: NOW)
    first = runner.run(batch_id=batch_id, feature_batch_id="FEAT_TEST")
    second = runner.run(batch_id=batch_id)
    assert first["status"] == "SUCCESS"
    assert second["status"] == "IDEMPOTENT_SUCCESS"
    assert Path(first["feature_summary_path"]).is_file()
    assert len(first["parquet_paths"]) == 5
    engine = create_engine(config.database_url)
    tables = inspect(engine).get_table_names()
    assert {"user_features", "item_features", "feature_definition",
            "feature_lineage"}.issubset(tables)
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT COUNT(*) FROM feature_lineage"
        )).scalar() > 0
        assert connection.execute(text(
            "SELECT COUNT(*) FROM feature_definition"
        )).scalar() > 0
