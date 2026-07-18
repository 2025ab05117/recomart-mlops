"""Typed YAML configuration for data profiling and validation."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from src.validation.errors import ValidationConfigurationError

DEFAULT_CONFIG_PATH = Path("configs/validation_rules.yaml")


@dataclass(frozen=True)
class RangeConfig:
    """Inclusive numeric range."""

    minimum: float
    maximum: float


@dataclass(frozen=True)
class RatingConfig:
    """Rating scale and optional unrated representation."""

    minimum: float
    maximum: float
    unrated_value: float | None = None
    purchase_minimum_rating: float | None = None


@dataclass(frozen=True)
class QualityWeights:
    """Weights used by the documented quality-score formula."""

    completeness: float
    uniqueness: float
    validity: float
    consistency: float


@dataclass(frozen=True)
class ValidationLogConfig:
    """Structured rotating-log settings."""

    level: str
    directory: Path
    filename: str
    max_bytes: int
    backup_count: int


@dataclass(frozen=True)
class ValidationConfig:
    """Complete validated configuration for one validation run."""

    project_root: Path
    config_path: Path
    config_version: str
    config_sha256: str
    config_snapshot: dict[str, Any]
    fail_fast: bool
    strict_quality: bool
    sample_error_count: int
    future_timestamp_tolerance_minutes: int
    popularity_max_age_hours: int
    raw_path: Path
    validated_path: Path
    quarantine_path: Path
    report_path: Path
    quality_weights: QualityWeights
    required_columns: dict[str, tuple[str, ...]]
    users_age: RangeConfig
    allowed_genders: tuple[str, ...]
    allowed_segments: tuple[str, ...]
    minimum_product_price: float
    product_rating: RatingConfig
    allowed_event_types: tuple[str, ...]
    purchase_quantity: RangeConfig
    purchase_rating: RatingConfig
    amount_tolerance: float
    popularity_score: RangeConfig
    popularity_rating: RatingConfig
    allowed_trends: tuple[str, ...]
    popularity_rating_tolerance: float
    total_ratings_tolerance: int
    logging: ValidationLogConfig


def load_validation_config(
    config_path: Path = DEFAULT_CONFIG_PATH,
    *,
    project_root: Path | None = None,
    environment: Mapping[str, str] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> ValidationConfig:
    """Load CLI/environment/YAML validation settings and validate them."""
    root = (
        project_root.resolve()
        if project_root is not None
        else Path(__file__).resolve().parents[2]
    )
    path = config_path if config_path.is_absolute() else root / config_path
    try:
        payload = path.read_bytes()
        raw = yaml.safe_load(payload)
    except (OSError, yaml.YAMLError) as exc:
        raise ValidationConfigurationError(
            f"Unable to load validation configuration: {path}"
        ) from exc
    if not isinstance(raw, dict):
        raise ValidationConfigurationError(
            "Validation configuration must be a YAML mapping."
        )
    env = os.environ if environment is None else environment
    cli = {
        key: value
        for key, value in (overrides or {}).items()
        if value is not None
    }
    try:
        validation = _mapping(raw, "validation")
        paths = _mapping(raw, "paths")
        weights = _mapping(raw, "quality_score")
        users = _mapping(raw, "users")
        products = _mapping(raw, "products")
        clickstream = _mapping(raw, "clickstream")
        purchases = _mapping(raw, "purchasehistory")
        popularity = _mapping(raw, "popularity")
        log_raw = _mapping(raw, "logging")
        config = ValidationConfig(
            project_root=root,
            config_path=path.resolve(),
            config_version=str(validation["config_version"]),
            config_sha256=hashlib.sha256(payload).hexdigest(),
            config_snapshot=raw,
            fail_fast=bool(validation.get("fail_fast", False)),
            strict_quality=bool(validation.get("strict_quality", False)),
            sample_error_count=int(validation["sample_error_count"]),
            future_timestamp_tolerance_minutes=int(
                validation["future_timestamp_tolerance_minutes"]
            ),
            popularity_max_age_hours=int(
                validation["popularity_max_age_hours"]
            ),
            raw_path=_resolve_path(
                root,
                _choose(
                    cli.get("raw_path"),
                    env.get("RECOMART_RAW_PATH"),
                    paths.get("raw"),
                    "data/raw",
                ),
            ),
            validated_path=_resolve_path(
                root,
                _choose(
                    cli.get("validated_path"),
                    env.get("RECOMART_VALIDATED_PATH"),
                    paths.get("validated"),
                    "data/validated",
                ),
            ),
            quarantine_path=_resolve_path(
                root,
                _choose(
                    cli.get("quarantine_path"),
                    env.get("RECOMART_QUARANTINE_PATH"),
                    paths.get("quarantine"),
                    "data/quarantine",
                ),
            ),
            report_path=_resolve_path(
                root,
                _choose(
                    cli.get("report_path"),
                    env.get("RECOMART_DQ_REPORT_PATH"),
                    paths.get("reports"),
                    "reports/data_quality",
                ),
            ),
            quality_weights=QualityWeights(
                float(weights["completeness_weight"]),
                float(weights["uniqueness_weight"]),
                float(weights["validity_weight"]),
                float(weights["consistency_weight"]),
            ),
            required_columns={
                "users": _strings(users, "required_columns"),
                "products": _strings(products, "required_columns"),
                "clickstream": _strings(clickstream, "required_columns"),
                "purchasehistory": _strings(
                    purchases, "required_columns"
                ),
                "popularity": _strings(popularity, "required_columns"),
            },
            users_age=_range(_mapping(users, "age")),
            allowed_genders=_strings(users, "allowed_genders"),
            allowed_segments=_strings(users, "allowed_segments"),
            minimum_product_price=float(products["minimum_price"]),
            product_rating=_rating(_mapping(products, "rating")),
            allowed_event_types=_strings(
                clickstream, "allowed_event_types"
            ),
            purchase_quantity=_range(_mapping(purchases, "quantity")),
            purchase_rating=_rating(_mapping(purchases, "rating")),
            amount_tolerance=float(purchases["amount_tolerance"]),
            popularity_score=_range(_mapping(popularity, "score")),
            popularity_rating=_rating(_mapping(popularity, "rating")),
            allowed_trends=_strings(popularity, "allowed_trends"),
            popularity_rating_tolerance=float(
                popularity["rating_tolerance"]
            ),
            total_ratings_tolerance=int(
                popularity["total_ratings_tolerance"]
            ),
            logging=ValidationLogConfig(
                level=str(
                    _choose(
                        cli.get("log_level"),
                        env.get("RECOMART_VALIDATION_LOG_LEVEL"),
                        log_raw.get("level"),
                        "INFO",
                    )
                ).upper(),
                directory=_resolve_path(
                    root,
                    _choose(
                        None,
                        env.get("RECOMART_VALIDATION_LOG_DIRECTORY"),
                        log_raw.get("directory"),
                        "logs/validation",
                    ),
                ),
                filename=str(log_raw["filename"]),
                max_bytes=int(log_raw["max_bytes"]),
                backup_count=int(log_raw["backup_count"]),
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationConfigurationError(
            f"Invalid validation configuration: {exc}"
        ) from exc
    _validate(config)
    return config


def _validate(config: ValidationConfig) -> None:
    weights = config.quality_weights
    total_weight = (
        weights.completeness
        + weights.uniqueness
        + weights.validity
        + weights.consistency
    )
    if abs(total_weight - 1.0) > 1e-9:
        raise ValidationConfigurationError(
            "Quality-score weights must sum to 1.0."
        )
    if any(
        value < 0
        for value in (
            weights.completeness,
            weights.uniqueness,
            weights.validity,
            weights.consistency,
        )
    ):
        raise ValidationConfigurationError(
            "Quality-score weights must not be negative."
        )
    if config.sample_error_count <= 0:
        raise ValidationConfigurationError(
            "sample_error_count must be positive."
        )
    if config.future_timestamp_tolerance_minutes < 0:
        raise ValidationConfigurationError(
            "Future timestamp tolerance cannot be negative."
        )
    if config.amount_tolerance < 0:
        raise ValidationConfigurationError(
            "Amount tolerance cannot be negative."
        )
    if config.logging.level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise ValidationConfigurationError("Invalid validation log level.")


def _mapping(mapping: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = mapping[key]
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a mapping")
    return value


def _strings(mapping: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = mapping[key]
    if not isinstance(value, list) or not value:
        raise ValueError(f"{key} must be a non-empty list")
    result = tuple(str(item).strip() for item in value)
    if any(not item for item in result):
        raise ValueError(f"{key} contains a blank value")
    return result


def _range(mapping: Mapping[str, Any]) -> RangeConfig:
    result = RangeConfig(
        float(mapping["minimum"]), float(mapping["maximum"])
    )
    if result.maximum < result.minimum:
        raise ValueError("range maximum is below minimum")
    return result


def _rating(mapping: Mapping[str, Any]) -> RatingConfig:
    return RatingConfig(
        minimum=float(mapping["minimum"]),
        maximum=float(mapping["maximum"]),
        unrated_value=(
            float(mapping["unrated_value"])
            if "unrated_value" in mapping
            else None
        ),
        purchase_minimum_rating=(
            float(mapping["purchase_minimum_rating"])
            if "purchase_minimum_rating" in mapping
            else None
        ),
    )


def _resolve_path(root: Path, value: Any) -> Path:
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _choose(*values: Any) -> Any:
    for value in values[:-1]:
        if value is not None and (
            not isinstance(value, str) or value.strip() != ""
        ):
            return value
    return values[-1] if values else None
