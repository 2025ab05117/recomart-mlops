"""Machine-readable and PDF model comparison reporting."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from src.modeling.errors import ModelPersistenceError


def write_reports(
    directory: Path,
    *,
    summary: dict[str, Any],
    comparison: dict[str, Any],
) -> list[Path]:
    """Write authoritative JSON reports and a readable multi-page PDF."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        summary_path = directory / "training_summary.json"
        comparison_path = directory / "model_comparison.json"
        pdf_path = directory / "model_performance_report.pdf"
        summary_path.write_text(
            json.dumps(_json_safe(summary), indent=2, default=str, allow_nan=False), encoding="utf-8"
        )
        comparison_path.write_text(
            json.dumps(_json_safe(comparison), indent=2, default=str, allow_nan=False), encoding="utf-8"
        )
        _pdf(pdf_path, summary, comparison)
        return [summary_path, comparison_path, pdf_path]
    except OSError as exc:
        raise ModelPersistenceError("Unable to generate model reports.") from exc


def _json_safe(value: Any) -> Any:
    """Convert non-finite metrics to JSON null recursively."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value

def _pdf(path: Path, summary: dict[str, Any],
         comparison: dict[str, Any]) -> None:
    styles = getSampleStyleSheet()
    story = [
        Spacer(1, 45 * mm),
        Paragraph("RecoMart Model Training and Evaluation", styles["Title"]),
        Spacer(1, 8 * mm),
        Paragraph(f"Model run: {summary['model_run_id']}", styles["Heading2"]),
        Paragraph(f"Feature batch: {summary['feature_batch_id']}",
                  styles["BodyText"]),
        Paragraph(f"Status: {summary['status']}", styles["BodyText"]),
        Paragraph(f"Recommended model: {comparison['recommended_model']}",
                  styles["Heading2"]),
        PageBreak(),
        Paragraph("Executive Summary", styles["Heading1"]),
        Paragraph(comparison["recommendation_reason"], styles["BodyText"]),
        Spacer(1, 5 * mm),
        Paragraph("Training Dataset", styles["Heading1"]),
        _table([
            ["Split", "Rows", "Explicit ratings"],
            *[
                [name, values["rows"], values["explicit_ratings"]]
                for name, values in summary["dataset"].items()
            ],
        ]),
        PageBreak(),
        Paragraph("Algorithms and Hyperparameters", styles["Heading1"]),
    ]
    for name, model in summary["models"].items():
        story.extend([
            Paragraph(name.replace("_", " ").title(), styles["Heading2"]),
            Paragraph(
                json.dumps(model["parameters"], indent=2),
                styles["Code"],
            ),
            Paragraph("Evaluation Metrics", styles["Heading3"]),
            _table([
                ["Metric", "Value"],
                *[
                    [metric, _number(value)]
                    for metric, value in model["metrics"].items()
                ],
            ]),
            Paragraph("Top Recommendations Example", styles["Heading3"]),
            _table([
                ["Product", "Score", "Rank"],
                *[
                    [row["product_id"], _number(row["score"]), row["rank"]]
                    for row in model["recommendation_example"][:10]
                ],
            ]),
            Spacer(1, 5 * mm),
        ])
    story.extend([
        PageBreak(),
        Paragraph("Metric Comparison", styles["Heading1"]),
        _table(comparison["comparison_table"]),
        Paragraph("Advantages and Limitations", styles["Heading1"]),
        Paragraph(
            "Collaborative filtering captures latent userâ€“item preference but "
            "depends on rating history and has cold-start limitations. "
            "Content similarity handles unseen-user-independent item discovery "
            "and is explainable through catalog attributes, but can over-specialize.",
            styles["BodyText"],
        ),
        Paragraph("Conclusion", styles["Heading1"]),
        Paragraph(comparison["recommendation_reason"], styles["BodyText"]),
    ])
    document = SimpleDocTemplate(
        str(path), pagesize=A4, rightMargin=15 * mm, leftMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
    )
    document.build(story)


def _table(rows: list[list[Any]]) -> Table:
    table = Table(rows, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#EDF3F8")]),
    ]))
    return table


def _number(value: Any) -> str:
    return f"{value:.6f}" if isinstance(value, float) else str(value)
