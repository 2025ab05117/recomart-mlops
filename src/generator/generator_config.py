"""Typed YAML configuration for MovieLens synthetic data generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src.generator.errors import GeneratorConfigurationError


@dataclass(frozen=True)
class GeneratorConfig:
    """Validated settings controlling source loading and generation."""

    project_root: Path
    source_directory: Path
    nested_directory_name: str
    output_directory: Path
    overwrite_existing: bool
    random_seed: int
    reference_time: datetime
    registration_lookback_years: int
    clickstream_lookback_hours: int
    purchase_delay_min_minutes: int
    purchase_delay_max_minutes: int
    session_inactivity_minutes: int
    minimum_price: float
    maximum_price: float
    customer_segments: tuple[str, ...]
    brands: tuple[str, ...]

    @classmethod
    def from_yaml(
        cls,
        config_path: Path,
        *,
        project_root: Path | None = None,
    ) -> "GeneratorConfig":
        """Load and validate settings from a YAML file.

        Args:
            config_path: YAML configuration path.
            project_root: Root for relative paths, inferred when omitted.

        Returns:
            Validated immutable configuration.

        Raises:
            GeneratorConfigurationError: If configuration is missing or invalid.
        """
        root = (
            project_root.resolve()
            if project_root is not None
            else Path(__file__).resolve().parents[2]
        )
        path = config_path if config_path.is_absolute() else root / config_path
        try:
            with path.open("r", encoding="utf-8") as stream:
                raw = yaml.safe_load(stream)
        except (OSError, yaml.YAMLError) as exc:
            raise GeneratorConfigurationError(
                f"Unable to load generator configuration: {path}"
            ) from exc
        if not isinstance(raw, dict):
            raise GeneratorConfigurationError(
                "Generator configuration must be a YAML mapping."
            )
        try:
            source = _mapping(raw, "source")
            output = _mapping(raw, "output")
            generation = _mapping(raw, "generation")
            delay = _mapping(generation, "purchase_delay_minutes")
            price = _mapping(generation, "price")
            config = cls(
                project_root=root,
                source_directory=_path(root, source["base_directory"]),
                nested_directory_name=str(source["nested_directory_name"]),
                output_directory=_path(root, output["incoming_directory"]),
                overwrite_existing=bool(output["overwrite_existing"]),
                random_seed=int(generation["random_seed"]),
                reference_time=_utc(generation["reference_time_utc"]),
                registration_lookback_years=int(
                    generation["registration_lookback_years"]
                ),
                clickstream_lookback_hours=int(
                    generation["clickstream_lookback_hours"]
                ),
                purchase_delay_min_minutes=int(delay["minimum"]),
                purchase_delay_max_minutes=int(delay["maximum"]),
                session_inactivity_minutes=int(
                    generation["session_inactivity_minutes"]
                ),
                minimum_price=float(price["minimum"]),
                maximum_price=float(price["maximum"]),
                customer_segments=_strings(generation, "customer_segments"),
                brands=_strings(generation, "brands"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GeneratorConfigurationError(
                f"Invalid generator configuration: {exc}"
            ) from exc
        config.validate()
        return config

    def validate(self) -> None:
        """Validate ranges and required collections."""
        if self.reference_time.tzinfo is None:
            raise GeneratorConfigurationError(
                "reference_time_utc must be timezone-aware."
            )
        positive_values = (
            self.registration_lookback_years,
            self.clickstream_lookback_hours,
            self.purchase_delay_min_minutes,
            self.session_inactivity_minutes,
        )
        if any(value <= 0 for value in positive_values):
            raise GeneratorConfigurationError(
                "Configured durations must be positive."
            )
        if self.purchase_delay_max_minutes < self.purchase_delay_min_minutes:
            raise GeneratorConfigurationError("Purchase delay range is invalid.")
        if self.minimum_price <= 0 or self.maximum_price < self.minimum_price:
            raise GeneratorConfigurationError("Price range is invalid.")
        if not self.customer_segments or not self.brands:
            raise GeneratorConfigurationError(
                "Customer segments and brands must not be empty."
            )


def _mapping(mapping: dict[str, Any], key: str) -> dict[str, Any]:
    value = mapping[key]
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a mapping")
    return value


def _strings(mapping: dict[str, Any], key: str) -> tuple[str, ...]:
    value = mapping[key]
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"{key} must be a non-empty string list")
    return tuple(item.strip() for item in value)


def _path(root: Path, value: Any) -> Path:
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _utc(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("reference_time_utc lacks an offset")
    return parsed.astimezone(timezone.utc)
