"""Typed preparation configuration loaded from YAML."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from src.preparation.errors import PreparationConfigurationError


@dataclass(frozen=True)
class PreparationConfig:
    """Validated settings for one preparation run."""

    root: Path
    path: Path
    version: str
    transformation_version: str
    sha256: str
    snapshot: dict[str, Any]
    validated_path: Path
    validation_report_path: Path
    output_path: Path
    report_path: Path
    unknown_category: str
    weights: dict[str, float]
    one_hot: dict[str, tuple[str, ...]]
    frequency: dict[str, tuple[str, ...]]
    standard_scale: dict[str, tuple[str, ...]]
    log_scale: dict[str, tuple[str, ...]]
    train_ratio: float
    validation_ratio: float
    test_ratio: float
    minimum_records: int
    heatmap_top_users: int
    heatmap_top_products: int
    top_items: int
    plot_dpi: int
    log_level: str
    log_directory: Path
    log_filename: str
    log_max_bytes: int
    log_backup_count: int


def load_preparation_config(
    path: Path = Path("configs/preparation.yaml"),
    *,
    project_root: Path | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> PreparationConfig:
    """Load and validate configuration; explicit overrides take precedence."""
    root = (project_root or Path(__file__).resolve().parents[2]).resolve()
    resolved = path if path.is_absolute() else root / path
    try:
        content = resolved.read_bytes()
        raw = yaml.safe_load(content)
        prep = raw["preparation"]
        enc = raw["encoding"]
        norm = raw["normalization"]
        split = raw["splitting"]
        eda = raw["eda"]
        log = raw["logging"]
    except (OSError, KeyError, TypeError, yaml.YAMLError) as exc:
        raise PreparationConfigurationError(
            f"Unable to load preparation configuration: {resolved}"
        ) from exc
    cli = {key: value for key, value in (overrides or {}).items()
           if value is not None}

    def resolve(value: object) -> Path:
        candidate = Path(str(value))
        return candidate.resolve() if candidate.is_absolute() else (
            root / candidate
        ).resolve()

    try:
        config = PreparationConfig(
            root=root,
            path=resolved.resolve(),
            version=str(prep["config_version"]),
            transformation_version=str(prep["transformation_version"]),
            sha256=hashlib.sha256(content).hexdigest(),
            snapshot=raw,
            validated_path=resolve(
                cli.get("validated_path", prep["validated_path"])
            ),
            validation_report_path=resolve(prep["validation_report_path"]),
            output_path=resolve(cli.get("output_path", prep["output_path"])),
            report_path=resolve(cli.get("report_path", prep["report_path"])),
            unknown_category=str(prep["unknown_category"]),
            weights={
                str(key): float(value)
                for key, value in raw["interactions"]["weights"].items()
            },
            one_hot={
                key: tuple(value) for key, value in enc["one_hot"].items()
            },
            frequency={
                key: tuple(value) for key, value in enc["frequency"].items()
            },
            standard_scale={
                key: tuple(value)
                for key, value in norm["standard_scale"].items()
            },
            log_scale={
                key: tuple(value)
                for key, value in norm["log1p_then_scale"].items()
            },
            train_ratio=float(split["train_ratio"]),
            validation_ratio=float(split["validation_ratio"]),
            test_ratio=float(split["test_ratio"]),
            minimum_records=int(split["minimum_records"]),
            heatmap_top_users=int(eda["heatmap_top_users"]),
            heatmap_top_products=int(eda["heatmap_top_products"]),
            top_items=int(eda["top_items_to_display"]),
            plot_dpi=int(eda["plot_dpi"]),
            log_level=str(cli.get("log_level", log["level"])).upper(),
            log_directory=resolve(log["directory"]),
            log_filename=str(log["filename"]),
            log_max_bytes=int(log["max_bytes"]),
            log_backup_count=int(log["backup_count"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PreparationConfigurationError(
            f"Invalid preparation configuration: {exc}"
        ) from exc
    if abs(
        config.train_ratio + config.validation_ratio + config.test_ratio - 1.0
    ) > 1e-9:
        raise PreparationConfigurationError("Split ratios must total 1.0.")
    if set(config.weights) != {"View", "Wishlist", "AddToCart", "Purchase"}:
        raise PreparationConfigurationError("Interaction weights are incomplete.")
    if config.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise PreparationConfigurationError("Invalid log level.")
    return config
