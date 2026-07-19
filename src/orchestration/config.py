"""Runtime configuration resolution and security-safe validation."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from src.orchestration.contracts import PipelineContext
from src.orchestration.errors import RuntimeConfigurationError

_BATCH = re.compile(r"^RECO_\d{8}_\d{6}_[A-Za-z0-9-]+$")

DEFAULTS: dict[str, Any] = {
    "run_generator": True,
    "batch_id": None,
    "storage": "local",
    "source_split": "train",
    "run_eda": True,
    "run_versioning": True,
    "train_algorithm": "all",
    "top_k": 10,
    "strict_quality": False,
}


def resolve_runtime_config(
    supplied: dict[str, Any] | None,
    *,
    dag_run_id: str,
    now: datetime | None = None,
) -> PipelineContext:
    """Validate DAG parameters and create the durable pipeline context."""
    values = {**DEFAULTS, **(supplied or {})}
    batch_id = values.get("batch_id") or None
    if batch_id and not _BATCH.fullmatch(str(batch_id)):
        raise RuntimeConfigurationError(
            "batch_id must use the RECO_YYYYMMDD_HHMMSS_suffix format."
        )
    if values["storage"] not in {"local", "s3"}:
        raise RuntimeConfigurationError("storage must be local or s3.")
    if values["source_split"] not in {"train", "all"}:
        raise RuntimeConfigurationError("source_split must be train or all.")
    if values["train_algorithm"] not in {
        "all", "collaborative", "content"
    }:
        raise RuntimeConfigurationError(
            "train_algorithm must be all, collaborative, or content."
        )
    top_k = int(values["top_k"])
    if top_k <= 0:
        raise RuntimeConfigurationError("top_k must be positive.")
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    pipeline_id = (
        f"PIPE_{timestamp.strftime('%Y%m%d_%H%M%S')}_"
        f"{uuid.uuid4().hex[:6]}"
    )
    return {
        "pipeline_run_id": pipeline_id,
        "airflow_dag_run_id": dag_run_id,
        "correlation_id": str(uuid.uuid4()),
        "batch_id": str(batch_id) if batch_id else None,
        "started_at": timestamp.isoformat().replace("+00:00", "Z"),
        # A supplied batch is an explicit reprocessing request.
        "run_generator": bool(values["run_generator"] and not batch_id),
        "storage": str(values["storage"]),
        "source_split": str(values["source_split"]),
        "run_eda": bool(values["run_eda"]),
        "run_versioning": bool(values["run_versioning"]),
        "train_algorithm": str(values["train_algorithm"]),
        "top_k": top_k,
        "strict_quality": bool(values["strict_quality"]),
    }


def mask_secrets(value: str) -> str:
    """Mask credentials embedded in common database and webhook URLs."""
    masked = re.sub(
        r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)"
        r"(?P<user>[^:/@\s]+):(?P<secret>[^@\s]+)@",
        r"\g<scheme>\g<user>:***@",
        value,
    )
    return re.sub(
        r"(?i)(token|password|secret|access_key)=([^&\s]+)",
        r"\1=***",
        masked,
    )
