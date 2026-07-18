"""Integration tests for manifest resolution, reports, and idempotency."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.validation.batch_repository import LocalRawBatchRepository
from src.validation.config import load_validation_config
from src.validation.validation_runner import ValidationRunner


def _write_raw_batch(root: Path) -> str:
    batch_id = "RECO_20260719_120000_test"
    user_id, product_id = 1, 10
    frames = {
        "users": pd.DataFrame([{
            "user_id": user_id, "age": 30, "gender": "M",
            "occupation": "engineer", "zipcode": "12345",
            "registration_date": "2026-01-01",
            "customer_segment": "Gold",
        }]),
        "products": pd.DataFrame([{
            "product_id": product_id, "product_name": "Product",
            "category": "Drama", "release_date": "01-Jan-1995",
            "price": 100.0, "brand": "Acme", "average_rating": 5.0,
            "total_ratings": 1,
        }]),
        "clickstream": pd.DataFrame([{
            "event_id": str(uuid.uuid4()), "user_id": user_id,
            "product_id": product_id, "event_type": "View",
            "timestamp": "2026-07-19T11:00:00Z",
            "session_id": str(uuid.uuid4()),
        }]),
        "purchasehistory": pd.DataFrame([{
            "order_id": str(uuid.uuid4()), "user_id": user_id,
            "product_id": product_id, "quantity": 1, "amount": 100.0,
            "rating": 5, "purchase_timestamp": "2026-07-19T11:30:00Z",
        }]),
        "popularity": pd.DataFrame([{
            "product_id": product_id, "average_rating": 5.0,
            "total_ratings": 1, "popularity_score": 100.0,
            "trend": "UP", "updated_at": "2026-07-19T11:45:00Z",
        }]),
    }
    records = []
    for name, frame in frames.items():
        suffix = ".csv" if name in {
            "users", "clickstream", "purchasehistory"
        } else ".json"
        path = root / "objects" / f"{name}{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        if suffix == ".csv":
            frame.to_csv(path, index=False)
        else:
            path.write_text(
                json.dumps(frame.to_dict(orient="records")),
                encoding="utf-8",
            )
        content = path.read_bytes()
        records.append({
            "source_type": "api" if name == "popularity" else "file",
            "dataset_type": name,
            "source_name": path.name,
            "destination_path": str(path.resolve()),
            "record_count": len(frame),
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "status": "SUCCESS",
        })
    manifest_dir = (
        root / "manifests" / "ingestion_date=2026-07-19"
        / "ingestion_hour=12" / f"batch_id={batch_id}"
    )
    manifest_dir.mkdir(parents=True)
    manifest = {
        "batch_id": batch_id,
        "run_id": str(uuid.uuid4()),
        "correlation_id": str(uuid.uuid4()),
        "started_at": "2026-07-19T12:00:00Z",
        "status": "SUCCESS",
        "files": records,
    }
    (manifest_dir / "ingestion_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return batch_id


def test_runner_generates_reports_manifest_and_reuses_outputs(
    tmp_path: Path,
) -> None:
    """One valid batch publishes all artifacts and reruns idempotently."""
    raw_root = tmp_path / "raw"
    batch_id = _write_raw_batch(raw_root)
    config = load_validation_config(
        overrides={
            "raw_path": raw_root,
            "validated_path": tmp_path / "validated",
            "quarantine_path": tmp_path / "quarantine",
            "report_path": tmp_path / "reports",
        }
    )
    clock = lambda: datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
    runner = ValidationRunner(
        config=config,
        repository=LocalRawBatchRepository(raw_root),
        utc_clock=clock,
    )

    first = runner.run(batch_id=batch_id)
    second = runner.run(batch_id=batch_id)

    assert first.exit_code(strict_quality=False) == 0
    assert first.manifest.status == "SUCCESS"
    assert first.manifest.overall_quality_score == 100.0
    assert Path(first.manifest.report_path).read_bytes().startswith(b"%PDF")
    assert Path(first.manifest.summary_path).is_file()
    assert second.manifest.idempotent
    assert second.manifest.validation_run_id == first.manifest.validation_run_id
    for dataset in first.manifest.datasets:
        assert Path(dataset["validated_path"]).is_file()
        assert Path(dataset["quarantine_path"]).is_file()

