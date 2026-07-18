"""Typed reproducible model-training configuration."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from src.modeling.errors import TrainingError


@dataclass(frozen=True)
class ModelingConfig:
    """Complete training, evaluation, tracking, and persistence settings."""

    root: Path
    path: Path
    sha256: str
    snapshot: dict[str, Any]
    database_url: str
    feature_path: Path
    prepared_path: Path
    model_path: Path
    report_path: Path
    experiment_name: str
    tracking_uri: str
    random_seed: int
    threshold: float
    top_k: int
    factors: int
    learning_rate: float
    regularization: float
    epochs: int
    content_top_k: int
    log_level: str
    log_directory: Path
    log_filename: str
    log_max_bytes: int
    log_backup_count: int


def load_modeling_config(
    path: Path = Path("configs/modeling.yaml"),
    *, project_root: Path | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> ModelingConfig:
    """Load YAML and apply safe CLI overrides."""
    root = (project_root or Path(__file__).resolve().parents[2]).resolve()
    resolved = path if path.is_absolute() else root / path
    try:
        content = resolved.read_bytes()
        raw = yaml.safe_load(content)
        model = raw["modeling"]
        collab = raw["collaborative"]
        content_cfg = raw["content_based"]
        log = raw["logging"]
    except (OSError, KeyError, TypeError, yaml.YAMLError) as exc:
        raise TrainingError(f"Unable to load modeling configuration: {resolved}") from exc
    cli = {key: value for key, value in (overrides or {}).items()
           if value is not None}

    def resolve(value: object) -> Path:
        candidate = Path(str(value))
        return candidate.resolve() if candidate.is_absolute() else (
            root / candidate
        ).resolve()

    def resolve_database_url(value: object) -> str:
        """Resolve a relative SQLite URL against the repository root."""
        url = str(value)
        prefix = "sqlite:///"
        if url.startswith(prefix) and not url.startswith("sqlite:////"):
            database_path = Path(url.removeprefix(prefix))
            if not database_path.is_absolute():
                database_path = root / database_path
            return f"{prefix}{database_path.resolve().as_posix()}"
        return url

    try:
        return ModelingConfig(
            root=root, path=resolved.resolve(),
            sha256=hashlib.sha256(content).hexdigest(), snapshot=raw,
            database_url=resolve_database_url(model["feature_database_url"]),
            feature_path=resolve(model["feature_path"]),
            prepared_path=resolve(model["prepared_path"]),
            model_path=resolve(model["model_path"]),
            report_path=resolve(model["report_path"]),
            experiment_name=str(model["experiment_name"]),
            tracking_uri=str(model["tracking_uri"]),
            random_seed=int(model["random_seed"]),
            threshold=float(model["relevance_rating_threshold"]),
            top_k=int(cli.get("top_k", model["top_k"])),
            factors=int(collab["factors"]),
            learning_rate=float(collab["learning_rate"]),
            regularization=float(collab["regularization"]),
            epochs=int(collab["epochs"]),
            content_top_k=int(content_cfg["top_k"]),
            log_level=str(log["level"]).upper(),
            log_directory=resolve(log["directory"]),
            log_filename=str(log["filename"]),
            log_max_bytes=int(log["max_bytes"]),
            log_backup_count=int(log["backup_count"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise TrainingError(f"Invalid modeling configuration: {exc}") from exc

