"""DVC stage adapter that snapshots existing manifest-driven artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.versioning.config import load_versioning_config
from src.versioning.discovery import discover_artifact


def main() -> int:
    """Write one deterministic stage snapshot used by `dvc repro`."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--config", type=Path, default=Path("configs/versioning.yaml")
    )
    args = parser.parse_args()
    config = load_versioning_config(args.config)
    observed = discover_artifact(config, args.stage)
    payload = {
        "dataset_name": observed.dataset_name,
        "batch_id": observed.batch_id,
        "run_id": observed.run_id,
        "pipeline_stage": observed.pipeline_stage,
        "created_at": observed.created_at,
        "checksum": observed.checksum,
        "record_count": observed.record_count,
        "schema_version": observed.schema_version,
        "storage_location": observed.storage_location,
        "manifest_path": observed.manifest_path,
        "configuration_hash": observed.configuration_hash,
        "transformation": observed.transformation,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
