"""One-run feature computation, persistence, snapshot, and lineage coordinator."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.feature_engineering.catalog import build_definitions, build_lineage
from src.feature_engineering.config import FeatureConfig
from src.feature_engineering.errors import FeatureConflictError
from src.feature_engineering.features import FeatureFrames, compute_all_features
from src.feature_engineering.loader import (
    load_prepared,
    resolve_prepared_batch,
    sha256_file,
)
from src.feature_engineering.storage import FeatureWarehouse

LOGGER = logging.getLogger(__name__)
Clock = Callable[[], datetime]


class FeatureRunner:
    """Generate leakage-safe features and publish them transactionally."""

    def __init__(
        self, config: FeatureConfig, *, utc_clock: Clock | None = None
    ) -> None:
        """Initialize the runner with injectable UTC time."""
        self.config = config
        self.clock = utc_clock or (lambda: datetime.now(timezone.utc))

    def initialize_database(self) -> dict[str, list[str]]:
        """Initialize database metadata schema and return its inventory."""
        warehouse = FeatureWarehouse(self.config)
        warehouse.initialize()
        return warehouse.table_inventory()

    def run(
        self,
        *,
        batch_id: str | None = None,
        feature_batch_id: str | None = None,
        write_parquet: bool = True,
    ) -> dict[str, Any]:
        """Execute one feature batch with identity-based idempotency."""
        timer = time.perf_counter()
        started = self.clock().astimezone(timezone.utc)
        prepared_batch = resolve_prepared_batch(
            self.config.prepared_path, batch_id
        )
        created_at = _utc(started)
        feature_batch = feature_batch_id or (
            f"FEAT_{started.strftime('%Y%m%d_%H%M%S')}_"
            f"{uuid.uuid4().hex[:6]}"
        )
        identity = self._identity(prepared_batch.batch_id,
                                  prepared_batch.checksums)
        warehouse = FeatureWarehouse(self.config)
        warehouse.initialize()
        existing = warehouse.find_identity(identity)
        if existing:
            existing["status"] = "IDEMPOTENT_SUCCESS"
            LOGGER.info("Matching feature batch already exists", extra={
                "feature_batch_id": existing["feature_batch_id"],
                "source_batch_id": prepared_batch.batch_id,
                "correlation_id": prepared_batch.correlation_id,
                "operation": "feature_run", "status": "IDEMPOTENT_SUCCESS",
            })
            return existing
        context = {
            "feature_batch_id": feature_batch,
            "source_batch_id": prepared_batch.batch_id,
            "correlation_id": prepared_batch.correlation_id,
        }
        LOGGER.info("Feature run started", extra={
            **context, "operation": "feature_run", "status": "STARTED"
        })
        prepared = load_prepared(prepared_batch)
        frames = compute_all_features(
            prepared, self.config,
            feature_batch_id=feature_batch,
            source_batch_id=prepared_batch.batch_id,
            created_at=created_at,
        )
        for group in ("users", "items", "user_items", "cooccurrence",
                      "similarity"):
            frame = getattr(frames, group)
            LOGGER.info("Feature group generated", extra={
                **context, "feature_group": group,
                "operation": "compute_features", "status": "SUCCESS",
                "records_in": frames.metadata["source_event_count"],
                "records_out": len(frame),
            })
        definitions = build_definitions(frames, self.config.version, created_at)
        lineage = build_lineage(
            definitions, frames,
            feature_batch_id=feature_batch,
            source_checksums=prepared_batch.checksums,
            transformation_version=self.config.version,
            generated_at=created_at,
        )
        completed = self.clock().astimezone(timezone.utc)
        counts = {
            "user_feature_count": len(frames.users),
            "item_feature_count": len(frames.items),
            "user_item_feature_count": len(frames.user_items),
            "cooccurrence_feature_count": len(frames.cooccurrence),
            "similarity_feature_count": len(frames.similarity),
        }
        batch_record = {
            "feature_batch_id": feature_batch,
            "source_batch_id": prepared_batch.batch_id,
            "preparation_run_id": prepared_batch.preparation_run_id,
            "feature_reference_timestamp": (
                frames.metadata["feature_reference_timestamp"]
            ),
            "feature_source_split": self.config.source_split,
            "started_at": _utc(started),
            "completed_at": _utc(completed),
            "status": "SUCCESS",
            **counts,
            "configuration_hash": self.config.sha256,
            "source_checksum": self._combined_checksum(
                prepared_batch.checksums
            ),
            "identity_hash": identity,
            "error_message": None,
            "created_at": created_at,
        }
        warehouse.persist(
            frames, batch_record=batch_record, definitions=definitions,
            lineage=lineage,
        )
        output_dir = (
            self.config.output_path
            / f"feature_date={started.date().isoformat()}"
            / f"feature_hour={started.strftime('%H')}"
            / f"feature_batch_id={feature_batch}"
        )
        parquet_paths = self._snapshots(frames, output_dir) if write_parquet else {}
        summary = self._summary(
            feature_batch, prepared_batch.batch_id, frames, counts,
            warehouse,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        summary_path = output_dir / "feature_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2, default=str),
                                encoding="utf-8")
        manifest = {
            **batch_record,
            "correlation_id": prepared_batch.correlation_id,
            "input_paths": {
                key: str(value) for key, value in prepared_batch.paths.items()
            },
            "input_checksums": prepared_batch.checksums,
            "configuration_hash": self.config.sha256,
            "feature_version": self.config.version,
            "feature_groups_generated": list(counts),
            "row_counts": counts,
            "column_counts": {
                "user": len(frames.users.columns),
                "item": len(frames.items.columns),
                "user_item": len(frames.user_items.columns),
                "cooccurrence": len(frames.cooccurrence.columns),
                "similarity": len(frames.similarity.columns),
            },
            "output_tables": list(warehouse.table_inventory()["tables"]),
            "parquet_paths": {
                key: str(value) for key, value in parquet_paths.items()
            },
            "output_checksums": {
                key: sha256_file(value) for key, value in parquet_paths.items()
            },
            "database_engine": warehouse.engine.dialect.name,
            "database_schema": warehouse.schema,
            "lineage_record_count": len(lineage),
            "feature_summary_path": str(summary_path),
            "warnings": (
                ["source_split=all is leakage-prone and for exploration only"]
                if self.config.source_split == "all" else []
            ),
            "errors": [],
        }
        manifest_path = output_dir / "feature_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, default=str), encoding="utf-8"
        )
        LOGGER.info("Feature run completed", extra={
            **context, "operation": "feature_run", "status": "SUCCESS",
            "records_in": frames.metadata["source_event_count"],
            "records_out": sum(counts.values()),
            "duration_ms": round((time.perf_counter() - timer) * 1000, 2),
        })
        return manifest

    def _snapshots(
        self, frames: FeatureFrames, directory: Path
    ) -> dict[str, Path]:
        directory.mkdir(parents=True, exist_ok=True)
        outputs = {
            "user_features": frames.users,
            "item_features": frames.items,
            "user_item_features": frames.user_items,
            "item_cooccurrence_features": frames.cooccurrence,
            "item_similarity_features": frames.similarity,
        }
        paths = {}
        for name, frame in outputs.items():
            path = directory / f"{name}.parquet"
            if path.exists():
                raise FeatureConflictError(f"Snapshot already exists: {path}")
            frame.to_parquet(path, index=False)
            paths[name] = path
        return paths

    def _identity(
        self, batch_id: str, checksums: dict[str, str]
    ) -> str:
        payload = json.dumps({
            "source_batch_id": batch_id,
            "source_split": self.config.source_split,
            "configuration": self.config.sha256,
            "feature_version": self.config.version,
            "input_checksums": checksums,
        }, sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _combined_checksum(checksums: dict[str, str]) -> str:
        return hashlib.sha256(json.dumps(
            checksums, sort_keys=True
        ).encode()).hexdigest()

    def _summary(
        self, feature_batch: str, source_batch: str,
        frames: FeatureFrames, counts: dict[str, int],
        warehouse: FeatureWarehouse,
    ) -> dict[str, Any]:
        return {
            "feature_batch_id": feature_batch,
            "source_batch_id": source_batch,
            "feature_reference_timestamp": (
                frames.metadata["feature_reference_timestamp"]
            ),
            "source_split": self.config.source_split,
            "generated_at": _utc(self.clock()),
            "user_feature_rows": counts["user_feature_count"],
            "item_feature_rows": counts["item_feature_count"],
            "user_item_feature_rows": counts["user_item_feature_count"],
            "cooccurrence_pair_rows": counts["cooccurrence_feature_count"],
            "similarity_pair_rows": counts["similarity_feature_count"],
            "feature_counts": {
                "user": len(frames.users.columns) - 4,
                "item": len(frames.items.columns) - 4,
                "user_item": len(frames.user_items.columns) - 4,
                "cooccurrence": len(frames.cooccurrence.columns) - 4,
                "similarity": len(frames.similarity.columns) - 4,
            },
            "null_metrics": {
                "user": frames.users.isna().sum().to_dict(),
                "item": frames.items.isna().sum().to_dict(),
                "user_item": frames.user_items.isna().sum().to_dict(),
            },
            "cold_start_users": int(
                frames.users.cold_start_user_flag.sum()
            ),
            "cold_start_items": int(
                frames.items.cold_start_item_flag.sum()
            ),
            "activity_thresholds": frames.metadata["activity_thresholds"],
            "database": {
                "engine": warehouse.engine.dialect.name,
                "schema": warehouse.schema,
            },
            "status": "SUCCESS",
        }


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
