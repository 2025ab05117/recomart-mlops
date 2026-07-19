"""Verify DAG discovery and print a compact setup result."""

from __future__ import annotations

import json
from pathlib import Path

from airflow.models import DagBag


def main() -> int:
    """Load the project DAG folder and return nonzero on import errors."""
    root = Path(__file__).resolve().parents[2]
    bag = DagBag(dag_folder=str(root / "dags"), include_examples=False)
    result = {
        "dag_ids": sorted(bag.dag_ids),
        "import_errors": {
            str(path): str(error)
            for path, error in bag.import_errors.items()
        },
    }
    print(json.dumps(result, indent=2))
    return 0 if (
        "recomart_end_to_end_pipeline" in bag.dag_ids
        and not bag.import_errors
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
