"""Typed YAML configuration for feature engineering."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from src.feature_engineering.errors import FeatureConfigurationError


@dataclass(frozen=True)
class FeatureConfig:
    """Validated settings for computation, storage, and reporting."""

    root: Path
    path: Path
    version: str
    sha256: str
    snapshot: dict[str, Any]
    prepared_path: Path
    output_path: Path
    source_split: str
    cold_user_minimum: int
    cold_item_users_minimum: int
    windows: tuple[int, ...]
    low_quantile: float
    high_quantile: float
    minimum_cooccurrence: int
    minimum_support: float
    maximum_neighbors: int
    top_k: int
    minimum_similarity: float
    similarity_weights: dict[str, float]
    database_url: str
    database_schema: str
    batch_size: int
    log_level: str
    log_directory: Path
    log_filename: str
    log_max_bytes: int
    log_backup_count: int


def load_feature_config(
    path: Path = Path("configs/feature_engineering.yaml"),
    *,
    project_root: Path | None = None,
    overrides: Mapping[str, Any] | None = None,
    environment: Mapping[str, str] | None = None,
) -> FeatureConfig:
    """Load CLI/environment/YAML settings with validation."""
    root = (project_root or Path(__file__).resolve().parents[2]).resolve()
    resolved = path if path.is_absolute() else root / path
    try:
        content = resolved.read_bytes()
        raw = yaml.safe_load(content)
        feature = raw["feature_engineering"]
        activity = raw["activity"]
        levels = raw["user_activity_level"]
        cooc = raw["cooccurrence"]
        similarity = raw["similarity"]
        database = raw["database"]
        logging = raw["logging"]
    except (OSError, KeyError, TypeError, yaml.YAMLError) as exc:
        raise FeatureConfigurationError(
            f"Unable to load feature configuration: {resolved}"
        ) from exc
    cli = {key: value for key, value in (overrides or {}).items()
           if value is not None}
    env = os.environ if environment is None else environment

    def resolve(value: object) -> Path:
        candidate = Path(str(value))
        return candidate.resolve() if candidate.is_absolute() else (
            root / candidate
        ).resolve()

    try:
        url = str(cli.get("database_url") or env.get(
            database["connection_env_var"]
        ) or database["sqlite_fallback_url"])
        config = FeatureConfig(
            root=root,
            path=resolved.resolve(),
            version=str(feature["feature_version"]),
            sha256=hashlib.sha256(content).hexdigest(),
            snapshot=raw,
            prepared_path=resolve(
                cli.get("prepared_path", feature["prepared_path"])
            ),
            output_path=resolve(cli.get("output_path", feature["output_path"])),
            source_split=str(
                cli.get("source_split", feature["feature_source_split"])
            ),
            cold_user_minimum=int(
                feature["cold_start_minimum_interactions"]
            ),
            cold_item_users_minimum=int(
                feature["cold_start_minimum_users"]
            ),
            windows=tuple(int(value) for value in activity["windows_days"]),
            low_quantile=float(levels["low_quantile"]),
            high_quantile=float(levels["high_quantile"]),
            minimum_cooccurrence=int(
                cooc["minimum_cooccurrence_count"]
            ),
            minimum_support=float(cooc["minimum_support"]),
            maximum_neighbors=int(cooc["maximum_neighbors_per_item"]),
            top_k=int(similarity["top_k_similar_items"]),
            minimum_similarity=float(
                similarity["minimum_combined_similarity"]
            ),
            similarity_weights={
                str(key): float(value)
                for key, value in similarity["weights"].items()
            },
            database_url=url,
            database_schema=str(database["schema"]),
            batch_size=int(database["batch_size"]),
            log_level=str(cli.get("log_level", logging["level"])).upper(),
            log_directory=resolve(logging["directory"]),
            log_filename=str(logging["filename"]),
            log_max_bytes=int(logging["max_bytes"]),
            log_backup_count=int(logging["backup_count"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise FeatureConfigurationError(
            f"Invalid feature configuration: {exc}"
        ) from exc
    if config.source_split not in {"train", "all"}:
        raise FeatureConfigurationError("source_split must be train or all.")
    if not 0 <= config.low_quantile < config.high_quantile <= 1:
        raise FeatureConfigurationError("Activity quantiles are invalid.")
    if abs(sum(config.similarity_weights.values()) - 1.0) > 1e-9:
        raise FeatureConfigurationError("Similarity weights must total 1.0.")
    if any(value <= 0 for value in config.windows) or config.top_k <= 0:
        raise FeatureConfigurationError("Windows and top_k must be positive.")
    if config.minimum_cooccurrence < 0 or config.minimum_support < 0:
        raise FeatureConfigurationError("Thresholds cannot be negative.")
    return config
