"""Model artifact and metadata persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import yaml

from src.modeling.errors import ModelPersistenceError


def save_model_bundle(
    model: object,
    directory: Path,
    *,
    metadata: dict[str, Any],
    configuration: dict[str, Any],
) -> list[Path]:
    """Persist a trained estimator, lineage metadata, and exact configuration."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        model_path = directory / "model.joblib"
        metadata_path = directory / "metadata.json"
        config_path = directory / "training_configuration.yaml"
        joblib.dump(model, model_path)
        metadata_path.write_text(
            json.dumps(metadata, indent=2, default=str), encoding="utf-8"
        )
        config_path.write_text(
            yaml.safe_dump(configuration, sort_keys=False), encoding="utf-8"
        )
        return [model_path, metadata_path, config_path]
    except (OSError, ValueError) as exc:
        raise ModelPersistenceError(
            f"Unable to save model bundle: {directory}"
        ) from exc
