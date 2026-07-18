"""Focused tests for RecoMart profiling and validation rules."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from src.validation.config import load_validation_config
from src.validation.errors import DatasetReadError
from src.validation.models import RawDatasetAsset
from src.validation.validators import DatasetValidator, read_raw_dataset

NOW = datetime(2026, 7, 19, 13, 0, tzinfo=timezone.utc)


@pytest.fixture
def validator() -> DatasetValidator:
    """Return a validator backed by the production rule configuration."""
    return DatasetValidator(load_validation_config())


@pytest.fixture
def valid_frames() -> dict[str, pd.DataFrame]:
    """Return mutually consistent, valid fixtures for every dataset."""
    user_id = 1
    product_id = 10
    event_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    return {
        "users": pd.DataFrame(
            [{
                "user_id": user_id,
                "age": 30,
                "gender": "M",
                "occupation": "engineer",
                "zipcode": "12345",
                "registration_date": "2026-01-01",
                "customer_segment": "Gold",
            }]
        ),
        "products": pd.DataFrame(
            [{
                "product_id": product_id,
                "product_name": "Product",
                "category": "Drama",
                "release_date": "01-Jan-1995",
                "price": 100.0,
                "brand": "Acme",
                "average_rating": 4.5,
                "total_ratings": 2,
            }]
        ),
        "clickstream": pd.DataFrame(
            [{
                "event_id": event_id,
                "user_id": user_id,
                "product_id": product_id,
                "event_type": "View",
                "timestamp": "2026-07-19T12:00:00Z",
                "session_id": session_id,
            }]
        ),
        "purchasehistory": pd.DataFrame(
            [{
                "order_id": str(uuid.uuid4()),
                "user_id": user_id,
                "product_id": product_id,
                "quantity": 2,
                "amount": 200.0,
                "rating": 5,
                "purchase_timestamp": "2026-07-19T12:30:00Z",
            }]
        ),
        "popularity": pd.DataFrame(
            [{
                "product_id": product_id,
                "average_rating": 4.5,
                "total_ratings": 2,
                "popularity_score": 90.0,
                "trend": "UP",
                "updated_at": "2026-07-19T12:30:00Z",
            }]
        ),
    }


def _asset(dataset: str) -> RawDatasetAsset:
    suffix = "csv" if dataset in {
        "users", "clickstream", "purchasehistory"
    } else "json"
    return RawDatasetAsset(
        dataset_type=dataset,
        source_name=f"{dataset}.{suffix}",
        source_path=f"raw/{dataset}.{suffix}",
        local_path=Path(f"{dataset}.{suffix}"),
        file_type=suffix,
        size_bytes=100,
        sha256="a" * 64,
        record_count=1,
    )


def _validate(
    validator: DatasetValidator,
    dataset: str,
    frame: pd.DataFrame,
    references: dict[str, pd.DataFrame],
):
    return validator.validate(
        dataset_type=dataset,
        frame=frame.reset_index(drop=True),
        asset=_asset(dataset),
        reference_frames=references,
        batch_id="RECO_TEST",
        validation_run_id=str(uuid.uuid4()),
        validation_time=NOW,
    )


@pytest.mark.parametrize(
    ("dataset", "rule_id"),
    [
        ("users", None),
        ("products", None),
        ("clickstream", None),
        ("purchasehistory", None),
        ("popularity", None),
    ],
)
def test_valid_datasets(
    validator: DatasetValidator,
    valid_frames: dict[str, pd.DataFrame],
    dataset: str,
    rule_id: str | None,
) -> None:
    """Valid, consistent fixtures pass all record-level error rules."""
    result = _validate(validator, dataset, valid_frames[dataset], valid_frames)
    assert result.invalid_records == 0
    assert not [
        rule for rule in result.rules
        if rule.severity == "ERROR" and rule.status == "FAILED"
    ]


@pytest.mark.parametrize(
    ("dataset", "column", "value", "expected_rule"),
    [
        ("users", "age", 121, "USERS_AGE_RANGE"),
        ("products", "price", 0, "PRODUCTS_PRICE_POSITIVE"),
        ("products", "average_rating", 6, "PRODUCTS_AVERAGE_RATING_RANGE"),
        ("clickstream", "event_type", "Buy", "CLICKSTREAM_EVENT_TYPE_ALLOWED"),
        ("clickstream", "event_id", "bad", "CLICKSTREAM_EVENT_UUID"),
        (
            "clickstream",
            "timestamp",
            "not-a-date",
            "CLICKSTREAM_TIMESTAMP_FORMAT",
        ),
        ("purchasehistory", "rating", 6, "PURCHASE_RATING_RANGE"),
        ("purchasehistory", "rating", 3, "PURCHASE_MINIMUM_RATING"),
        ("purchasehistory", "quantity", 0, "PURCHASE_QUANTITY_RANGE"),
        ("purchasehistory", "amount", 199, "PURCHASE_AMOUNT_CONSISTENCY"),
        ("popularity", "popularity_score", 101, "POPULARITY_SCORE_RANGE"),
        ("popularity", "trend", "STABLE", "POPULARITY_TREND_ALLOWED"),
        (
            "popularity",
            "average_rating",
            4.0,
            "POPULARITY_PRODUCT_STATISTICS",
        ),
    ],
)
def test_configured_rule_failures(
    validator: DatasetValidator,
    valid_frames: dict[str, pd.DataFrame],
    dataset: str,
    column: str,
    value: object,
    expected_rule: str,
) -> None:
    """Range, format, business, and consistency failures quarantine rows."""
    frame = valid_frames[dataset].copy()
    frame.loc[0, column] = value
    result = _validate(validator, dataset, frame, valid_frames)
    failed_ids = {
        rule.rule_id for rule in result.rules if rule.status == "FAILED"
    }
    assert expected_rule in failed_ids
    assert result.invalid_records == 1


@pytest.mark.parametrize(
    ("dataset", "key", "rule_fragment"),
    [
        ("users", "user_id", "USER_ID_UNIQUE"),
        ("products", "product_id", "PRODUCT_ID_UNIQUE"),
        ("clickstream", "event_id", "EVENT_ID_UNIQUE"),
        ("purchasehistory", "order_id", "ORDER_ID_UNIQUE"),
        ("popularity", "product_id", "PRODUCT_ID_UNIQUE"),
    ],
)
def test_duplicate_rows_and_business_keys(
    validator: DatasetValidator,
    valid_frames: dict[str, pd.DataFrame],
    dataset: str,
    key: str,
    rule_fragment: str,
) -> None:
    """Entire duplicates and duplicate business keys are both reported."""
    frame = pd.concat(
        [valid_frames[dataset], valid_frames[dataset]], ignore_index=True
    )
    result = _validate(validator, dataset, frame, valid_frames)
    failed_ids = {
        rule.rule_id for rule in result.rules if rule.status == "FAILED"
    }
    assert any(rule.endswith("DUPLICATE_ROWS") for rule in failed_ids)
    assert any(rule_fragment in rule for rule in failed_ids)
    assert result.invalid_records == 2
    assert "validation_error_codes" in result.invalid_frame.columns


def test_missing_required_column_skips_dependent_rules(
    validator: DatasetValidator,
    valid_frames: dict[str, pd.DataFrame],
) -> None:
    """A missing column is diagnostic and dependent checks are skipped."""
    frame = valid_frames["users"].drop(columns=["age"])
    result = _validate(validator, "users", frame, valid_frames)
    statuses = {rule.rule_id: rule.status for rule in result.rules}
    assert statuses["USERS_SCHEMA_REQUIRED_COLUMNS"] == "FAILED"
    assert statuses["USERS_AGE_RANGE"] == "SKIPPED"
    assert result.critical_schema_failure


def test_missing_required_value_is_quarantined(
    validator: DatasetValidator,
    valid_frames: dict[str, pd.DataFrame],
) -> None:
    """Required nulls remain visible and are never imputed."""
    frame = valid_frames["users"].copy()
    frame.loc[0, "occupation"] = None
    result = _validate(validator, "users", frame, valid_frames)
    assert result.invalid_records == 1
    assert pd.isna(result.invalid_frame.loc[0, "occupation"])


@pytest.mark.parametrize(
    ("dataset", "column", "value", "rule_id"),
    [
        ("clickstream", "user_id", 999, "CLICKSTREAM_USER_REFERENCE"),
        ("clickstream", "product_id", 999, "CLICKSTREAM_PRODUCT_REFERENCE"),
    ],
)
def test_orphan_clickstream_references(
    validator: DatasetValidator,
    valid_frames: dict[str, pd.DataFrame],
    dataset: str,
    column: str,
    value: int,
    rule_id: str,
) -> None:
    """Orphan user and product references are quarantined."""
    frame = valid_frames[dataset].copy()
    frame.loc[0, column] = value
    result = _validate(validator, dataset, frame, valid_frames)
    assert rule_id in {
        rule.rule_id for rule in result.rules if rule.status == "FAILED"
    }
    assert result.invalid_records == 1


def test_empty_dataset_is_a_critical_failure(
    validator: DatasetValidator,
    valid_frames: dict[str, pd.DataFrame],
) -> None:
    """Empty inputs fail cleanly without preventing diagnostic output."""
    empty = valid_frames["users"].iloc[0:0]
    result = _validate(validator, "users", empty, valid_frames)
    assert result.critical_schema_failure
    assert any(
        rule.rule_id == "USERS_NON_EMPTY" and rule.status == "FAILED"
        for rule in result.rules
    )


def test_invalid_json_is_rejected(tmp_path: Path) -> None:
    """Malformed JSON raises the documented dataset read exception."""
    source = tmp_path / "products.json"
    source.write_text("{", encoding="utf-8")
    payload = source.read_bytes()
    asset = RawDatasetAsset(
        dataset_type="products",
        source_name=source.name,
        source_path=str(source),
        local_path=source,
        file_type="json",
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        record_count=0,
    )
    with pytest.raises(DatasetReadError):
        read_raw_dataset(asset)


def test_profile_and_summary_are_json_serializable(
    validator: DatasetValidator,
    valid_frames: dict[str, pd.DataFrame],
) -> None:
    """Profiles contain required metrics and serialize for automation."""
    result = _validate(
        validator, "products", valid_frames["products"], valid_frames
    )
    profile = result.profile
    assert profile["total_record_count"] == 1
    assert profile["total_column_count"] == 8
    assert "numeric_statistics" in profile
    assert "categorical_statistics" in profile
    json.dumps(result.to_summary_dict())

