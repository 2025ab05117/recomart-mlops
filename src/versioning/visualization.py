"""Static lineage graph rendering without external Graphviz binaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx

from src.versioning.errors import LineageError


def render_lineage(report: dict[str, Any], path: Path) -> None:
    """Render a readable directed PNG from the machine-readable graph."""
    graph = nx.DiGraph()
    nodes = report["pipeline_graph"]["nodes"]
    edges = report["pipeline_graph"]["edges"]
    for node in nodes:
        graph.add_node(node["id"], stage=node["stage"])
    for edge in edges:
        graph.add_edge(edge["parent_version"], edge["child_version"])
    main_order = [
        "incoming", "raw", "validated", "prepared", "features", "models",
        "mlflow",
    ]
    positions: dict[str, tuple[float, float]] = {}
    branches = {"eda_reports": 1.5, "model_reports": -1.5}
    for node, values in graph.nodes(data=True):
        stage = values["stage"]
        if stage in main_order:
            positions[node] = (0.0, -float(main_order.index(stage)))
        else:
            parent_y = -float(
                main_order.index("prepared" if stage == "eda_reports" else "models")
            )
            positions[node] = (branches.get(stage, 1.5), parent_y - 0.35)
    labels = {
        node: (
            values["stage"].replace("_", " ").title()
            + "\n"
            + node[-16:]
        )
        for node, values in graph.nodes(data=True)
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        figure, axis = plt.subplots(figsize=(12, 10))
        nx.draw_networkx(
            graph, pos=positions, labels=labels, ax=axis,
            node_color="#DDEBFF", edge_color="#4E6E8E",
            node_size=3300, font_size=8, arrowsize=18,
            linewidths=1.2,
        )
        axis.set_title("RecoMart Dataset and Model Lineage", fontsize=16)
        axis.axis("off")
        figure.tight_layout()
        figure.savefig(path, dpi=160, bbox_inches="tight")
        plt.close(figure)
    except (OSError, ValueError) as exc:
        raise LineageError(f"Unable to render lineage graph: {path}") from exc
