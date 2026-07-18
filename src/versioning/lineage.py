"""Lineage graph construction and consistency verification."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import networkx as nx

from src.versioning.errors import LineageError


def utc_now() -> str:
    """Return a UTC ISO-8601 timestamp."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_lineage(
    current: dict[str, dict[str, Any]],
    transformations: dict[str, str],
    *,
    model_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build dataset edges plus terminal model-to-MLflow run edges."""
    edges: list[dict[str, Any]] = []
    for child in current.values():
        parent_version = child.get("parent_dataset_version")
        if not parent_version:
            continue
        raw_id = (
            f"{parent_version}|{child['dataset_version']}|"
            f"{child['batch_id']}|{transformations[child['dataset_name']]}"
        )
        edges.append({
            "lineage_id": hashlib.sha256(raw_id.encode()).hexdigest()[:32],
            "parent_version": parent_version,
            "child_version": child["dataset_version"],
            "pipeline_stage": child["pipeline_stage"],
            "transformation": transformations[child["dataset_name"]],
            "batch_id": child["batch_id"],
            "created_at": child["created_at"],
            "manifest": child["manifest_path"],
            "checksum": child["checksum"],
        })
    if model_details:
        model_version = current["models"]["dataset_version"]
        for name, model in model_details.get("models", {}).items():
            mlflow = model.get("mlflow", {})
            run_id = mlflow.get("run_id")
            if not run_id:
                continue
            raw_id = f"{model_version}|mlflow:{run_id}|{name}"
            edges.append({
                "lineage_id": hashlib.sha256(raw_id.encode()).hexdigest()[:32],
                "parent_version": model_version,
                "child_version": f"mlflow-run:{run_id}",
                "pipeline_stage": "mlflow",
                "transformation": f"log_{name}_experiment",
                "batch_id": model_details.get("training_batch_id", ""),
                "created_at": model_details.get("completed_at", ""),
                "manifest": current["models"]["manifest_path"],
                "checksum": current["models"]["checksum"],
                "artifact_uri": mlflow.get("artifact_uri"),
            })
    nodes = [
        {
            "id": item["dataset_version"],
            "dataset_name": item["dataset_name"],
            "stage": item["pipeline_stage"],
            "batch_id": item["batch_id"],
            "checksum": item["checksum"],
        }
        for item in current.values()
    ]
    for edge in edges:
        if edge["child_version"].startswith("mlflow-run:"):
            nodes.append({
                "id": edge["child_version"],
                "dataset_name": "mlflow_run",
                "stage": "mlflow",
                "batch_id": edge["batch_id"],
                "checksum": None,
            })
    return {
        "lineage_schema_version": "1.0",
        "generated_at": utc_now(),
        "pipeline_graph": {"nodes": nodes, "edges": edges},
        "transformation_history": edges,
    }


def verify_lineage(report: dict[str, Any]) -> list[str]:
    """Return lineage graph errors; an empty list means valid lineage."""
    graph = nx.DiGraph()
    nodes = report.get("pipeline_graph", {}).get("nodes", [])
    edges = report.get("pipeline_graph", {}).get("edges", [])
    for node in nodes:
        graph.add_node(node["id"])
    errors: list[str] = []
    for edge in edges:
        parent = edge["parent_version"]
        child = edge["child_version"]
        if parent not in graph:
            errors.append(f"Missing parent node: {parent}")
        if child not in graph:
            errors.append(f"Missing child node: {child}")
        graph.add_edge(parent, child)
    if not nx.is_directed_acyclic_graph(graph):
        errors.append("Lineage graph contains a cycle.")
    return errors
