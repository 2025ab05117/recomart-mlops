"""One-run preparation orchestration and immutable publication."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from src.preparation.config import PreparationConfig
from src.preparation.eda import generate_eda
from src.preparation.errors import (
    PreparationConflictError,
    PreparationStorageError,
)
from src.preparation.loader import (
    file_sha256,
    load_validated_datasets,
    resolve_validated_batch,
)
from src.preparation.transformations import PreparedData, prepare_frames

LOGGER = logging.getLogger(__name__)
Clock = Callable[[], datetime]


class PreparationRunner:
    """Resolve, prepare, publish, analyze, and manifest one validated batch."""

    def __init__(
        self,
        config: PreparationConfig,
        *,
        utc_clock: Clock | None = None,
    ) -> None:
        """Initialize with externalized settings and an injectable UTC clock."""
        self.config = config
        self.clock = utc_clock or (lambda: datetime.now(timezone.utc))

    def run(
        self, *, batch_id: str | None = None, run_eda: bool = True
    ) -> dict[str, Any]:
        """Execute one idempotent preparation batch."""
        started_clock = time.perf_counter()
        started = self.clock().astimezone(timezone.utc)
        batch = resolve_validated_batch(
            self.config.validation_report_path, batch_id
        )
        identity = self._identity(batch.batch_id, batch.checksums)
        existing = self._find_existing(batch.batch_id)
        if existing:
            if existing.get("identity_sha256") != identity:
                raise PreparationConflictError(
                    "Prepared destination exists with incompatible lineage."
                )
            existing["idempotent"] = True
            LOGGER.info(
                "Preparation outputs already exist and match inputs",
                extra={
                    "batch_id": batch.batch_id,
                    "preparation_run_id": existing["preparation_run_id"],
                    "correlation_id": batch.correlation_id,
                    "operation": "prepare_batch",
                    "status": "IDEMPOTENT_SUCCESS",
                },
            )
            return existing
        run_id = str(uuid.uuid4())
        context = {
            "batch_id": batch.batch_id,
            "preparation_run_id": run_id,
            "correlation_id": batch.correlation_id,
        }
        LOGGER.info("Preparation started", extra={
            **context, "operation": "prepare_batch", "status": "STARTED"
        })
        frames = load_validated_datasets(batch)
        for name, frame in frames.items():
            LOGGER.info("Validated dataset loaded", extra={
                **context, "dataset_type": name, "operation": "load_validated",
                "status": "SUCCESS", "records_in": len(frame),
                "records_out": len(frame), "records_removed": 0,
            })
        prepared = prepare_frames(
            frames,
            self.config,
            batch_id=batch.batch_id,
            reference_time=started,
        )
        partition = (
            f"processing_date={started.date().isoformat()}",
            f"processing_hour={started.strftime('%H')}",
            f"batch_id={batch.batch_id}",
        )
        output_dir = self.config.output_path.joinpath(*partition)
        report_dir = self.config.report_path.joinpath(*partition)
        output_dir.mkdir(parents=True, exist_ok=True)
        report_dir.mkdir(parents=True, exist_ok=True)
        output_paths = self._write_outputs(prepared, output_dir)
        generated_at = _utc(started)
        if run_eda:
            eda_summary, plot_paths = generate_eda(
                prepared, report_dir, self.config,
                batch_id=batch.batch_id,
                preparation_run_id=run_id,
                generated_at=generated_at,
            )
        else:
            eda_summary, plot_paths = {}, []
        summary = self._summary(
            batch.batch_id, run_id, prepared, output_paths, report_dir
        )
        summary_path = output_dir / "preparation_summary.json"
        _write_json(summary_path, summary)
        completed = self.clock().astimezone(timezone.utc)
        warnings = []
        if frames["popularity"].empty:
            warnings.append(
                "Validated popularity dataset is empty; optional product "
                "popularity enrichment was unavailable."
            )
        manifest = {
            "batch_id": batch.batch_id,
            "preparation_run_id": run_id,
            "correlation_id": batch.correlation_id,
            "validation_run_id": batch.validation_run_id,
            "validation_manifest_path": str(batch.manifest_path),
            "source_dataset_paths": {
                key: str(value) for key, value in batch.paths.items()
            },
            "source_checksums": batch.checksums,
            "started_at": _utc(started),
            "completed_at": _utc(completed),
            "status": "COMPLETED_WITH_WARNINGS" if warnings else "SUCCESS",
            "warnings": warnings,
            "cleaning_actions": prepared.cleaning_actions,
            "records_read": {
                name: len(frame) for name, frame in frames.items()
            },
            "records_removed": {
                item["dataset"]: item["records_removed"]
                for item in prepared.cleaning_actions
            },
            "records_produced": {
                "users_prepared": len(prepared.users),
                "products_prepared": len(prepared.products),
                "interactions_prepared": len(prepared.interactions),
                "user_product_interactions": len(prepared.aggregated),
                "user_item_implicit": len(prepared.implicit_matrix),
                "user_item_ratings": len(prepared.ratings_matrix),
                "train": len(prepared.train),
                "validation": len(prepared.validation),
                "test": len(prepared.test),
            },
            "encoding_methods": prepared.encoder_metadata,
            "normalization_methods": prepared.scaler_metadata,
            "split_boundaries": prepared.split_metadata,
            "matrix_statistics": prepared.matrix_statistics,
            "output_dataset_paths": {
                key: str(value) for key, value in output_paths.items()
            },
            "output_checksums": {
                key: file_sha256(value) for key, value in output_paths.items()
            },
            "preparation_summary_path": str(summary_path),
            "eda_summary_path": str(report_dir / "eda_summary.json")
            if run_eda else None,
            "plot_paths": [str(path) for path in plot_paths],
            "configuration_version": self.config.version,
            "configuration_sha256": self.config.sha256,
            "transformation_version": self.config.transformation_version,
            "identity_sha256": identity,
            "errors": [],
            "idempotent": False,
        }
        manifest_path = output_dir / "preparation_manifest.json"
        _write_json(manifest_path, manifest)
        LOGGER.info("Preparation completed", extra={
            **context, "operation": "prepare_batch",
            "status": manifest["status"],
            "records_in": sum(len(frame) for frame in frames.values()),
            "records_out": len(prepared.interactions),
            "records_removed": sum(
                item["records_removed"] for item in prepared.cleaning_actions
            ),
            "duration_ms": round(
                (time.perf_counter() - started_clock) * 1000, 2
            ),
        })
        return manifest

    def _write_outputs(
        self, data: PreparedData, directory: Path
    ) -> dict[str, Path]:
        artifacts = {
            "users_prepared": data.users,
            "products_prepared": data.products,
            "interactions_prepared": data.interactions,
            "user_product_interactions": data.aggregated,
            "user_item_implicit": data.implicit_matrix,
            "user_item_ratings": data.ratings_matrix,
            "train": data.train,
            "validation": data.validation,
            "test": data.test,
        }
        paths: dict[str, Path] = {}
        try:
            for name, frame in artifacts.items():
                path = directory / f"{name}.parquet"
                _write_parquet(path, frame)
                paths[name] = path
            metadata = {
                "category_encoder": data.encoder_metadata.get("one_hot", {}),
                "demographic_encoders": data.encoder_metadata,
                "numerical_scalers": data.scaler_metadata,
            }
            for name, payload in metadata.items():
                path = directory / f"{name}.json"
                _write_json(path, payload)
                paths[name] = path
        except (OSError, ValueError) as exc:
            raise PreparationStorageError(
                f"Unable to publish prepared outputs: {directory}"
            ) from exc
        return paths

    def _identity(
        self, batch_id: str, checksums: dict[str, str]
    ) -> str:
        payload = json.dumps({
            "batch_id": batch_id,
            "checksums": checksums,
            "configuration": self.config.sha256,
            "transformation": self.config.transformation_version,
        }, sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()

    def _find_existing(self, batch_id: str) -> dict[str, Any] | None:
        candidates = list(
            self.config.output_path.rglob(
                f"batch_id={batch_id}/preparation_manifest.json"
            )
        )
        if not candidates:
            return None
        if len(candidates) > 1:
            raise PreparationConflictError(
                f"Multiple preparation manifests exist for {batch_id}."
            )
        return json.loads(candidates[0].read_text(encoding="utf-8"))

    @staticmethod
    def _summary(
        batch_id: str,
        run_id: str,
        data: PreparedData,
        paths: dict[str, Path],
        report_dir: Path,
    ) -> dict[str, Any]:
        return {
            "batch_id": batch_id,
            "preparation_run_id": run_id,
            "records": {
                "users": len(data.users),
                "products": len(data.products),
                "interactions": len(data.interactions),
                "aggregated_user_product_pairs": len(data.aggregated),
                "train": len(data.train),
                "validation": len(data.validation),
                "test": len(data.test),
            },
            "matrix_statistics": data.matrix_statistics,
            "split": data.split_metadata,
            "cleaning_actions": data.cleaning_actions,
            "outputs": {key: str(value) for key, value in paths.items()},
            "eda_directory": str(report_dir),
        }


def _write_parquet(path: Path, frame: pd.DataFrame) -> None:
    """Write Parquet atomically to prevent partial visibility."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent, suffix=".parquet", delete=False
    ) as stream:
        temporary = Path(stream.name)
    try:
        frame.to_parquet(temporary, index=False)
        if path.exists():
            if file_sha256(path) != file_sha256(temporary):
                raise PreparationConflictError(f"Conflicting output: {path}")
            temporary.unlink()
        else:
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, indent=2, default=str)
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise PreparationConflictError(f"Conflicting output: {path}")
        return
    path.write_text(content, encoding="utf-8")


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
