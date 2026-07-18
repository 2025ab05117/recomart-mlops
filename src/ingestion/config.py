"""Validated ingestion configuration with explicit precedence handling."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from src.ingestion.errors import ConfigurationError

DEFAULT_CONFIG_PATH = Path("configs/ingestion.yaml")


@dataclass(frozen=True)
class RequestConfig:
    """HTTP timeout and retry policy."""

    connect_timeout_seconds: float
    read_timeout_seconds: float
    max_attempts: int
    backoff_seconds: tuple[float, ...]


@dataclass(frozen=True)
class S3Config:
    """S3 or S3-compatible destination settings."""

    bucket: str
    prefix: str
    region: str | None
    endpoint_url: str | None
    profile: str | None
    max_attempts: int
    backoff_seconds: tuple[float, ...]


@dataclass(frozen=True)
class LogConfig:
    """Structured console and rotating-file log settings."""

    level: str
    directory: Path
    filename: str
    max_bytes: int
    backup_count: int


@dataclass(frozen=True)
class IngestionConfig:
    """All validated settings required for one ingestion execution."""

    project_root: Path
    input_path: Path
    required_files: tuple[str, ...]
    popularity_api_url: str
    request: RequestConfig
    storage_type: str
    local_raw_path: Path
    s3: S3Config
    logging: LogConfig

    @property
    def destination_label(self) -> str:
        """Return the safe destination description used by the manifest."""
        if self.storage_type == "local":
            try:
                return self.local_raw_path.relative_to(self.project_root).as_posix()
            except ValueError:
                return str(self.local_raw_path)
        prefix = self.s3.prefix.strip("/")
        suffix = f"/{prefix}" if prefix else ""
        return f"s3://{self.s3.bucket}{suffix}"


def load_ingestion_config(
    config_path: Path = DEFAULT_CONFIG_PATH,
    *,
    project_root: Path | None = None,
    environment: Mapping[str, str] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> IngestionConfig:
    """Load configuration using CLI, environment, YAML, then defaults.

    Args:
        config_path: YAML path, relative to the project root when needed.
        project_root: Optional root used to resolve local paths.
        environment: Environment mapping, defaulting to ``os.environ``.
        overrides: Command-line values; ``None`` values are ignored.

    Returns:
        A validated immutable configuration.

    Raises:
        ConfigurationError: If configuration is missing or invalid.
    """
    root = (
        project_root.resolve()
        if project_root is not None
        else Path(__file__).resolve().parents[2]
    )
    resolved_path = (
        config_path if config_path.is_absolute() else root / config_path
    )
    try:
        with resolved_path.open("r", encoding="utf-8") as stream:
            raw = yaml.safe_load(stream)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(
            f"Unable to load ingestion configuration: {resolved_path}"
        ) from exc
    if not isinstance(raw, dict):
        raise ConfigurationError("Ingestion YAML must be a mapping.")

    env = os.environ if environment is None else environment
    cli = {} if overrides is None else {
        key: value for key, value in overrides.items() if value is not None
    }
    try:
        ingestion = _mapping(raw, "ingestion")
        request_raw = _mapping(ingestion, "request")
        storage = _mapping(raw, "storage")
        local = _mapping(storage, "local")
        s3_raw = _mapping(storage, "s3")
        logging_raw = _mapping(raw, "logging")

        input_value = _choose(
            cli.get("input_path"),
            env.get("RECOMART_INPUT_PATH"),
            ingestion.get("input_path"),
            "data/incoming",
        )
        raw_value = _choose(
            cli.get("output_path"),
            env.get("RECOMART_RAW_PATH"),
            local.get("raw_path"),
            "data/raw",
        )
        log_directory = _choose(
            None,
            env.get("RECOMART_INGESTION_LOG_DIRECTORY"),
            logging_raw.get("directory"),
            "logs/ingestion",
        )
        config = IngestionConfig(
            project_root=root,
            input_path=_resolve_path(root, input_value),
            required_files=_required_files(ingestion.get("required_files")),
            popularity_api_url=str(
                _choose(
                    cli.get("popularity_api_url"),
                    env.get("RECOMART_POPULARITY_API_URL"),
                    ingestion.get("popularity_api_url"),
                    "http://localhost:8000/api/v1/popularity",
                )
            ),
            request=RequestConfig(
                connect_timeout_seconds=float(
                    request_raw.get("connect_timeout_seconds", 5)
                ),
                read_timeout_seconds=float(
                    request_raw.get("read_timeout_seconds", 30)
                ),
                max_attempts=int(request_raw.get("max_attempts", 3)),
                backoff_seconds=_number_tuple(
                    request_raw.get("backoff_seconds", [1, 2, 4])
                ),
            ),
            storage_type=str(
                _choose(
                    cli.get("storage"),
                    env.get("RECOMART_STORAGE_TYPE"),
                    storage.get("type"),
                    "local",
                )
            ).lower(),
            local_raw_path=_resolve_path(root, raw_value),
            s3=S3Config(
                bucket=str(
                    _choose(
                        cli.get("bucket"),
                        env.get("RECOMART_S3_BUCKET"),
                        s3_raw.get("bucket"),
                        "",
                    )
                ).strip(),
                prefix=str(
                    _choose(
                        cli.get("prefix"),
                        env.get("RECOMART_S3_PREFIX"),
                        s3_raw.get("prefix"),
                        "raw",
                    )
                ).strip("/"),
                region=_optional(
                    _choose(
                        cli.get("region"),
                        env.get("AWS_DEFAULT_REGION"),
                        s3_raw.get("region"),
                        None,
                    )
                ),
                endpoint_url=_optional(
                    _choose(
                        cli.get("endpoint_url"),
                        env.get("RECOMART_S3_ENDPOINT_URL"),
                        s3_raw.get("endpoint_url"),
                        None,
                    )
                ),
                profile=_optional(
                    _choose(
                        cli.get("profile"),
                        env.get("AWS_PROFILE"),
                        s3_raw.get("profile"),
                        None,
                    )
                ),
                max_attempts=int(s3_raw.get("max_attempts", 3)),
                backoff_seconds=_number_tuple(
                    s3_raw.get("backoff_seconds", [1, 2, 4])
                ),
            ),
            logging=LogConfig(
                level=str(
                    _choose(
                        cli.get("log_level"),
                        env.get("RECOMART_LOG_LEVEL"),
                        logging_raw.get("level"),
                        "INFO",
                    )
                ).upper(),
                directory=_resolve_path(root, log_directory),
                filename=str(logging_raw.get("filename", "ingestion.log")),
                max_bytes=int(logging_raw.get("max_bytes", 5_242_880)),
                backup_count=int(logging_raw.get("backup_count", 5)),
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigurationError(f"Invalid ingestion configuration: {exc}") from exc
    _validate(config)
    return config


def _validate(config: IngestionConfig) -> None:
    if config.storage_type not in {"local", "s3"}:
        raise ConfigurationError("storage type must be 'local' or 's3'.")
    if config.storage_type == "s3" and not config.s3.bucket:
        raise ConfigurationError("S3 storage requires a destination bucket.")
    if config.request.connect_timeout_seconds <= 0:
        raise ConfigurationError("HTTP connect timeout must be positive.")
    if config.request.read_timeout_seconds <= 0:
        raise ConfigurationError("HTTP read timeout must be positive.")
    if config.request.max_attempts <= 0:
        raise ConfigurationError("HTTP max_attempts must be positive.")
    if config.s3.max_attempts <= 0:
        raise ConfigurationError("S3 max_attempts must be positive.")
    if config.logging.level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise ConfigurationError("Unsupported ingestion log level.")
    if config.logging.max_bytes <= 0 or config.logging.backup_count < 0:
        raise ConfigurationError("Rotating log settings are invalid.")
    if not config.required_files:
        raise ConfigurationError("At least one required input file is needed.")


def _mapping(mapping: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = mapping[key]
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a mapping")
    return value


def _required_files(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError("required_files must be a non-empty list")
    names = tuple(str(item).strip() for item in value)
    if any(
        not name
        or Path(name).name != name
        or Path(name).suffix.lower() not in {".csv", ".json"}
        for name in names
    ):
        raise ValueError("required_files contains an unsafe or invalid name")
    return names


def _number_tuple(value: Any) -> tuple[float, ...]:
    if not isinstance(value, list):
        raise ValueError("backoff_seconds must be a list")
    result = tuple(float(item) for item in value)
    if any(item < 0 for item in result):
        raise ValueError("backoff values must not be negative")
    return result


def _resolve_path(root: Path, value: Any) -> Path:
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _optional(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _choose(*values: Any) -> Any:
    for value in values[:-1]:
        if value is not None and (
            not isinstance(value, str) or value.strip() != ""
        ):
            return value
    return values[-1] if values else None

