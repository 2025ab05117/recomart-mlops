"""Unit and integration coverage for preparation."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.preparation.config import load_preparation_config
from src.preparation.errors import (
    PreparationConfigurationError,
    ValidatedBatchNotFoundError,
)
from src.preparation.loader import (
    load_validated_datasets,
    resolve_validated_batch,
)
from src.preparation.runner import PreparationRunner
from src.preparation.transformations import (
    aggregate_interactions,
    build_interactions,
    build_matrices,
    clean_datasets,
    chronological_split,
    encode_categoricals,
    normalize_numericals,
    prepare_frames,
)

NOW = datetime(2026, 7, 19, 12, tzinfo=timezone.utc)


@pytest.fixture
def config():
    """Load production preparation configuration."""
    return load_preparation_config()


@pytest.fixture
def frames() -> dict[str, pd.DataFrame]:
    """Return valid, deterministic preparation inputs."""
    users = pd.DataFrame([
        {"user_id": 1, "age": 25, "gender": " M ",
         "occupation": " Engineer ", "zipcode": "12345",
         "registration_date": "2025-01-01", "customer_segment": "gold"},
        {"user_id": 2, "age": 40, "gender": "F",
         "occupation": "artist", "zipcode": "23456",
         "registration_date": "2024-01-01", "customer_segment": "Premium"},
    ])
    products = pd.DataFrame([
        {"product_id": 10, "product_name": "A", "category": "Drama",
         "release_date": "01-Jan-2000", "price": 100.0, "brand": "Acme",
         "average_rating": 4.5, "total_ratings": 10},
        {"product_id": 20, "product_name": "B", "category": "Comedy",
         "release_date": None, "price": 200.0, "brand": "Acme",
         "average_rating": 4.0, "total_ratings": 4},
    ])
    clickstream = pd.DataFrame([
        {"event_id": str(uuid.uuid4()), "user_id": 1, "product_id": 10,
         "event_type": "View", "timestamp": "2026-07-19T09:00:00Z",
         "session_id": str(uuid.uuid4())},
        {"event_id": str(uuid.uuid4()), "user_id": 2, "product_id": 20,
         "event_type": "Wishlist", "timestamp": "2026-07-19T10:00:00Z",
         "session_id": str(uuid.uuid4())},
        {"event_id": str(uuid.uuid4()), "user_id": 1, "product_id": 20,
         "event_type": "AddToCart", "timestamp": "2026-07-19T11:00:00Z",
         "session_id": str(uuid.uuid4())},
    ])
    purchases = pd.DataFrame([
        {"order_id": str(uuid.uuid4()), "user_id": 1, "product_id": 10,
         "quantity": 2, "amount": 200.0, "rating": 5,
         "purchase_timestamp": "2026-07-19T11:30:00Z"}
    ])
    popularity = pd.DataFrame([
        {"product_id": 10, "average_rating": 4.5, "total_ratings": 10,
         "popularity_score": 90.0, "trend": "UP",
         "updated_at": "2026-07-19T11:00:00Z"}
    ])
    return {
        "users": users, "products": products, "clickstream": clickstream,
        "purchasehistory": purchases, "popularity": popularity,
    }


def test_cleaning_strings_timestamps_and_duplicates(frames) -> None:
    """Cleaning standardizes strings/timestamps and documents duplicates."""
    frames["users"] = pd.concat([frames["users"], frames["users"].iloc[[0]]])
    cleaned, actions = clean_datasets(
        frames, batch_id="B", reference_time=NOW, unknown="Unknown"
    )
    assert cleaned["users"].loc[0, "gender"] == "M"
    assert cleaned["users"].loc[0, "occupation"] == "engineer"
    assert str(cleaned["clickstream"]["timestamp"].dtype).endswith("UTC]")
    assert next(x for x in actions if x["dataset"] == "users")[
        "records_removed"
    ] == 1


def test_encodings_and_unknown_handling(config, frames) -> None:
    """Nominal fields use one-hot and brand uses frequency encoding."""
    cleaned, _ = clean_datasets(
        frames, batch_id="B", reference_time=NOW, unknown="Unknown"
    )
    users, products, metadata = encode_categoricals(
        cleaned["users"], cleaned["products"], config
    )
    assert any(column.startswith("gender__") for column in users)
    assert "brand_frequency" in products
    assert "Unknown" in metadata["one_hot"]["users.gender"]["categories"]


def test_normalization_and_log_transform(config, frames) -> None:
    """Standard and log1p scaling create finite reproducible features."""
    cleaned, _ = clean_datasets(
        frames, batch_id="B", reference_time=NOW, unknown="Unknown"
    )
    output, metadata = normalize_numericals(
        {"users": cleaned["users"], "products": cleaned["products"]}, config
    )
    assert np.isclose(output["users"]["age_scaled"].mean(), 0)
    assert "products.total_ratings" in metadata
    assert metadata["products.total_ratings"]["method"] == "log1p_standard"


def test_interactions_weights_and_timestamp_features(config, frames) -> None:
    """Unified interactions preserve explicit ratings and map configured weights."""
    cleaned, _ = clean_datasets(
        frames, batch_id="B", reference_time=NOW, unknown="Unknown"
    )
    interactions = build_interactions(
        cleaned["clickstream"], cleaned["purchasehistory"], config.weights, "B"
    )
    purchase = interactions[interactions.interaction_type == "Purchase"].iloc[0]
    assert purchase.interaction_weight == 5.0
    assert purchase.explicit_rating == 5
    assert {"hour_sin", "day_of_week_cos"}.issubset(interactions.columns)


def test_aggregation_matrices_sparsity_and_missing_semantics(config, frames) -> None:
    """Matrices persist observed pairs and define zero/NaN missing semantics."""
    cleaned, _ = clean_datasets(
        frames, batch_id="B", reference_time=NOW, unknown="Unknown"
    )
    interactions = build_interactions(
        cleaned["clickstream"], cleaned["purchasehistory"], config.weights, "B"
    )
    aggregate = aggregate_interactions(interactions)
    implicit, ratings, stats, matrix = build_matrices(
        aggregate, cleaned["users"], cleaned["products"]
    )
    assert matrix.toarray()[1, 0] == 0
    assert len(ratings) == 1
    assert implicit["implicit_score"].gt(0).all()
    assert stats["possible_user_product_pairs"] == 4
    assert np.isclose(stats["sparsity"], 0.25)


def test_chronological_split_has_no_leakage(config, frames) -> None:
    """All train timestamps precede validation and test timestamps."""
    cleaned, _ = clean_datasets(
        frames, batch_id="B", reference_time=NOW, unknown="Unknown"
    )
    interactions = build_interactions(
        cleaned["clickstream"], cleaned["purchasehistory"], config.weights, "B"
    )
    train, validation, test, metadata = chronological_split(
        interactions, config
    )
    assert train.event_timestamp.max() <= validation.event_timestamp.min()
    assert validation.event_timestamp.max() <= test.event_timestamp.min()
    assert metadata["strategy"] == "chronological"


def test_invalid_ratios_fail(tmp_path: Path) -> None:
    """Configuration rejects split ratios that do not total one."""
    source = Path("configs/preparation.yaml").read_text(encoding="utf-8")
    path = tmp_path / "bad.yaml"
    path.write_text(source.replace("test_ratio: 0.15", "test_ratio: 0.20"))
    with pytest.raises(PreparationConfigurationError):
        load_preparation_config(path)


def _write_validated_batch(tmp_path: Path, frames) -> tuple[Path, str]:
    report = tmp_path / "quality"
    batch_id = "RECO_TEST"
    datasets = []
    for name, frame in frames.items():
        suffix = ".csv" if name in {
            "users", "clickstream", "purchasehistory"
        } else ".json"
        path = tmp_path / "validated" / f"{name}{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        if suffix == ".csv":
            frame.to_csv(path, index=False)
        else:
            path.write_text(json.dumps(frame.to_dict(orient="records")))
        datasets.append({
            "dataset_type": name,
            "validated_path": str(path),
        })
    manifest_dir = (
        report / "validation_date=2026-07-19" / "validation_hour=12"
        / f"batch_id={batch_id}"
    )
    manifest_dir.mkdir(parents=True)
    manifest = {
        "batch_id": batch_id,
        "validation_run_id": str(uuid.uuid4()),
        "correlation_id": str(uuid.uuid4()),
        "started_at": "2026-07-19T12:00:00Z",
        "status": "SUCCESS",
        "datasets": datasets,
    }
    (manifest_dir / "validation_manifest.json").write_text(
        json.dumps(manifest)
    )
    return report, batch_id


def test_loading_latest_and_missing_dataset(tmp_path: Path, frames) -> None:
    """Manifest resolution loads validated assets and rejects missing files."""
    report, batch_id = _write_validated_batch(tmp_path, frames)
    batch = resolve_validated_batch(report)
    assert batch.batch_id == batch_id
    assert len(load_validated_datasets(batch)) == 5
    batch.paths["users"].unlink()
    with pytest.raises(ValidatedBatchNotFoundError):
        resolve_validated_batch(report, batch_id)


def test_runner_parquet_eda_manifest_and_idempotency(
    tmp_path: Path, frames
) -> None:
    """The complete local runner publishes outputs, plots, and reuses them."""
    report, batch_id = _write_validated_batch(tmp_path, frames)
    config = load_preparation_config(
        overrides={
            "output_path": tmp_path / "prepared",
            "report_path": tmp_path / "eda",
        }
    )
    object.__setattr__(config, "validation_report_path", report)
    runner = PreparationRunner(config, utc_clock=lambda: NOW)
    first = runner.run(batch_id=batch_id)
    second = runner.run(batch_id=batch_id)
    assert first["status"] == "SUCCESS"
    assert second["idempotent"]
    assert len(first["plot_paths"]) == 9
    for path in first["output_dataset_paths"].values():
        assert Path(path).is_file()
    manifest = next((tmp_path / "prepared").rglob("preparation_manifest.json"))
    assert json.loads(manifest.read_text())["batch_id"] == batch_id


def test_prepare_frames_empty_interactions_fails(config, frames) -> None:
    """An empty interaction set fails instead of publishing meaningless splits."""
    frames["clickstream"] = frames["clickstream"].iloc[0:0]
    frames["purchasehistory"] = frames["purchasehistory"].iloc[0:0]
    with pytest.raises(Exception):
        prepare_frames(frames, config, batch_id="B", reference_time=NOW)
