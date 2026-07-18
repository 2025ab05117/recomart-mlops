"""Authoritative JSON summary and human-readable PDF quality reporting."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src.validation.config import ValidationConfig
from src.validation.errors import ReportGenerationError
from src.validation.models import DatasetValidationResult


def build_quality_summary(
    *,
    batch_id: str,
    validation_run_id: str,
    correlation_id: str,
    started_at: str,
    completed_at: str,
    status: str,
    raw_manifest_path: str,
    overall_quality_score: float,
    results: list[DatasetValidationResult],
    config: ValidationConfig,
    technical_errors: list[dict[str, str]],
) -> dict[str, Any]:
    """Build the complete machine-readable profiling and validation report."""
    total_records = sum(result.total_records for result in results)
    valid_records = sum(result.valid_records for result in results)
    invalid_records = sum(result.invalid_records for result in results)
    all_rules = [rule for result in results for rule in result.rules]
    return {
        "report_version": "1.0",
        "batch_id": batch_id,
        "validation_run_id": validation_run_id,
        "correlation_id": correlation_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "status": status,
        "raw_manifest_path": raw_manifest_path,
        "configuration_version": config.config_version,
        "configuration_sha256": config.config_sha256,
        "quality_score_formula": {
            "completeness_weight": config.quality_weights.completeness,
            "uniqueness_weight": config.quality_weights.uniqueness,
            "validity_weight": config.quality_weights.validity,
            "consistency_weight": config.quality_weights.consistency,
        },
        "executive_summary": {
            "datasets_checked": len(results),
            "total_records": total_records,
            "valid_records": valid_records,
            "invalid_records": invalid_records,
            "failed_rules": sum(rule.status == "FAILED" for rule in all_rules),
            "warnings": sum(rule.status == "WARNING" for rule in all_rules),
            "skipped_rules": sum(rule.status == "SKIPPED" for rule in all_rules),
            "overall_quality_score": overall_quality_score,
        },
        "datasets": [result.to_summary_dict() for result in results],
        "cross_dataset_rules": [
            rule.to_dict()
            for rule in all_rules
            if rule.category in {"Referential Integrity", "Consistency"}
        ],
        "recommendations": _recommendations(results),
        "technical_errors": technical_errors,
        "validation_configuration": config.config_snapshot,
    }


def generate_pdf_report(
    *,
    summary: dict[str, Any],
    results: list[DatasetValidationResult],
) -> bytes:
    """Render a readable multi-page PDF with tables and page numbers."""
    buffer = BytesIO()
    try:
        document = SimpleDocTemplate(
            buffer,
            pagesize=landscape(A4),
            rightMargin=14 * mm,
            leftMargin=14 * mm,
            topMargin=14 * mm,
            bottomMargin=14 * mm,
            title="RecoMart Data Quality Report",
            author="RecoMart MLOps",
        )
        styles = getSampleStyleSheet()
        styles.add(
            ParagraphStyle(
                name="CoverTitle",
                parent=styles["Title"],
                fontSize=28,
                leading=34,
                alignment=TA_CENTER,
                textColor=colors.HexColor("#17365D"),
                spaceAfter=18,
            )
        )
        styles.add(
            ParagraphStyle(
                name="Section",
                parent=styles["Heading1"],
                textColor=colors.HexColor("#17365D"),
                spaceBefore=8,
                spaceAfter=8,
            )
        )
        styles.add(
            ParagraphStyle(
                name="Small",
                parent=styles["BodyText"],
                fontSize=7.5,
                leading=9,
            )
        )
        story: list[Any] = []
        executive = summary["executive_summary"]
        story.extend(
            [
                Spacer(1, 35 * mm),
                Paragraph("RecoMart Data Quality Report", styles["CoverTitle"]),
                Paragraph(
                    f"Batch ID: <b>{_escape(summary['batch_id'])}</b>",
                    styles["Heading2"],
                ),
                Paragraph(
                    "Validation run: "
                    f"{_escape(summary['validation_run_id'])}",
                    styles["BodyText"],
                ),
                Paragraph(
                    f"Completed: {_escape(summary['completed_at'])}",
                    styles["BodyText"],
                ),
                Spacer(1, 8 * mm),
                Paragraph(
                    f"Status: <b>{_escape(summary['status'])}</b>",
                    styles["Heading2"],
                ),
                Paragraph(
                    "Overall quality score: "
                    f"<b>{executive['overall_quality_score']:.2f}/100</b>",
                    styles["Heading2"],
                ),
                PageBreak(),
                Paragraph("Executive Summary", styles["Section"]),
            ]
        )
        executive_rows = [
            ["Metric", "Value"],
            ["Datasets checked", executive["datasets_checked"]],
            ["Total records", executive["total_records"]],
            ["Valid records", executive["valid_records"]],
            ["Invalid records", executive["invalid_records"]],
            ["Failed rules", executive["failed_rules"]],
            ["Warnings", executive["warnings"]],
            ["Overall quality score", executive["overall_quality_score"]],
        ]
        story.append(_table(executive_rows, [65 * mm, 45 * mm]))
        conclusion = (
            "All configured ERROR rules passed."
            if summary["status"] == "SUCCESS"
            else (
                "Validation completed with data-quality findings. Review "
                "quarantine outputs and failed rules before preparation."
            )
        )
        story.extend(
            [
                Spacer(1, 5 * mm),
                Paragraph(f"<b>Conclusion:</b> {conclusion}", styles["BodyText"]),
                Spacer(1, 6 * mm),
                Paragraph("Dataset Summary", styles["Section"]),
                _dataset_summary_table(results, styles["Small"]),
                PageBreak(),
            ]
        )
        for result in results:
            story.extend(_dataset_detail(result, styles))
            story.append(PageBreak())

        story.append(Paragraph("Validation Issues", styles["Section"]))
        issues_by_category: dict[str, list[Any]] = defaultdict(list)
        for result in results:
            for rule in result.rules:
                if rule.status in {"FAILED", "WARNING", "SKIPPED"}:
                    issues_by_category[rule.category].append(rule)
        if not issues_by_category:
            story.append(Paragraph("No validation issues detected.", styles["BodyText"]))
        for category in sorted(issues_by_category):
            story.append(Paragraph(category, styles["Heading2"]))
            rows: list[list[Any]] = [
                [
                    "Rule",
                    "Severity",
                    "Dataset",
                    "Column",
                    "Failed",
                    "Failure %",
                    "Description",
                    "Samples",
                ]
            ]
            for rule in issues_by_category[category]:
                rows.append(
                    [
                        rule.rule_id,
                        rule.severity,
                        rule.dataset_type,
                        rule.column_name or "—",
                        rule.failed_record_count,
                        f"{rule.failure_percentage:.2f}",
                        _paragraph(rule.message, styles["Small"]),
                        _paragraph(
                            ", ".join(
                                str(value)
                                for value in rule.sample_failed_values[:5]
                            )
                            or "—",
                            styles["Small"],
                        ),
                    ]
                )
            story.append(
                _table(
                    rows,
                    [
                        34 * mm,
                        17 * mm,
                        22 * mm,
                        28 * mm,
                        15 * mm,
                        18 * mm,
                        70 * mm,
                        45 * mm,
                    ],
                )
            )
            story.append(Spacer(1, 4 * mm))

        story.extend(
            [
                PageBreak(),
                Paragraph("Cross-Dataset Integrity", styles["Section"]),
                _cross_dataset_table(summary, styles["Small"]),
                Spacer(1, 6 * mm),
                Paragraph("Recommendations", styles["Section"]),
            ]
        )
        recommendations = summary["recommendations"]
        if recommendations:
            for recommendation in recommendations:
                story.append(
                    Paragraph(
                        f"• {_escape(recommendation)}", styles["BodyText"]
                    )
                )
        else:
            story.append(
                Paragraph(
                    "No corrective recommendations were generated.",
                    styles["BodyText"],
                )
            )
        story.extend(
            [
                PageBreak(),
                Paragraph("Appendix", styles["Section"]),
                Paragraph(
                    f"<b>Configuration version:</b> "
                    f"{_escape(summary['configuration_version'])}",
                    styles["BodyText"],
                ),
                Paragraph(
                    f"<b>Configuration SHA-256:</b> "
                    f"{_escape(summary['configuration_sha256'])}",
                    styles["BodyText"],
                ),
                Paragraph(
                    f"<b>Raw manifest:</b> "
                    f"{_escape(summary['raw_manifest_path'])}",
                    styles["Small"],
                ),
                Spacer(1, 4 * mm),
                Paragraph("Source Checksums", styles["Heading2"]),
                _checksum_table(results, styles["Small"]),
                Spacer(1, 5 * mm),
                Paragraph("Rule Identifiers", styles["Heading2"]),
                _rule_identifier_table(results, styles["Small"]),
                Spacer(1, 5 * mm),
                Paragraph(
                    "<b>Software:</b> RecoMart MLOps validation framework, "
                    "Python 3.12 target, Pandas-based rules.",
                    styles["BodyText"],
                ),
            ]
        )
        document.build(
            story,
            onFirstPage=_page_number,
            onLaterPages=_page_number,
        )
    except Exception as exc:
        raise ReportGenerationError(
            "Unable to generate the PDF data-quality report."
        ) from exc
    return buffer.getvalue()


def _dataset_summary_table(
    results: list[DatasetValidationResult], small_style: ParagraphStyle
) -> Table:
    rows: list[list[Any]] = [
        [
            "Dataset",
            "Total",
            "Valid",
            "Invalid",
            "Missing",
            "Duplicates",
            "Schema",
            "Range",
            "Format",
            "Referential",
            "Score",
            "Status",
        ]
    ]
    for result in results:
        categories = _failed_categories(result)
        missing = sum(result.profile["missing_value_count"].values())
        duplicates = result.profile["duplicate_row_count"]
        status = "PASS" if result.invalid_records == 0 else "ISSUES"
        rows.append(
            [
                result.dataset_type,
                result.total_records,
                result.valid_records,
                result.invalid_records,
                missing,
                duplicates,
                categories["Schema"],
                categories["Range"],
                categories["Format"],
                categories["Referential Integrity"],
                f"{result.quality_score:.2f}",
                status,
            ]
        )
    return _table(
        rows,
        [
            27 * mm,
            18 * mm,
            18 * mm,
            18 * mm,
            18 * mm,
            20 * mm,
            18 * mm,
            18 * mm,
            18 * mm,
            22 * mm,
            18 * mm,
            20 * mm,
        ],
    )


def _dataset_detail(
    result: DatasetValidationResult, styles: dict[str, ParagraphStyle]
) -> list[Any]:
    profile = result.profile
    elements: list[Any] = [
        Paragraph(
            f"Dataset Profile: {_escape(result.dataset_type)}",
            styles["Section"],
        ),
        Paragraph(
            f"<b>Source:</b> {_escape(result.source_path)}",
            styles["Small"],
        ),
        Paragraph(
            f"Records: {result.total_records} | Valid: {result.valid_records} | "
            f"Invalid: {result.invalid_records} | "
            f"Quality: {result.quality_score:.2f}",
            styles["BodyText"],
        ),
        Spacer(1, 3 * mm),
        Paragraph("Schema Comparison", styles["Heading2"]),
    ]
    schema_rows = [["Column", "Inferred", "Expected", "Missing", "Unique"]]
    for column in profile["column_names"]:
        schema_rows.append(
            [
                column,
                profile["inferred_data_types"].get(column, "—"),
                profile["expected_data_types"].get(column, "unexpected"),
                profile["missing_value_count"].get(column, 0),
                profile["unique_value_count"].get(column, 0),
            ]
        )
    elements.append(
        _table(schema_rows, [45 * mm, 35 * mm, 35 * mm, 25 * mm, 25 * mm])
    )
    elements.extend(
        [
            Spacer(1, 4 * mm),
            Paragraph("Numeric Statistics", styles["Heading2"]),
            _statistics_table(profile["numeric_statistics"], styles["Small"]),
            Spacer(1, 4 * mm),
            Paragraph("Timestamp Ranges", styles["Heading2"]),
            _timestamp_table(profile["timestamp_statistics"], styles["Small"]),
            Spacer(1, 4 * mm),
            Paragraph("Categorical Statistics", styles["Heading2"]),
            _categorical_table(
                profile["categorical_statistics"], styles["Small"]
            ),
            Spacer(1, 4 * mm),
            Paragraph("Rule Outcomes", styles["Heading2"]),
            _rule_table(result, styles["Small"]),
        ]
    )
    return elements


def _statistics_table(
    statistics: dict[str, dict[str, Any]], style: ParagraphStyle
) -> Table:
    rows: list[list[Any]] = [
        ["Column", "Min", "Max", "Mean", "Median", "Std Dev", "P05/P95"]
    ]
    for column, values in statistics.items():
        percentiles = values.get("percentiles", {})
        rows.append(
            [
                column,
                values.get("minimum", "—"),
                values.get("maximum", "—"),
                values.get("mean", "—"),
                values.get("median", "—"),
                values.get("standard_deviation", "—"),
                f"{percentiles.get('p05', '—')} / "
                f"{percentiles.get('p95', '—')}",
            ]
        )
    if len(rows) == 1:
        rows.append(["No numeric columns", "—", "—", "—", "—", "—", "—"])
    return _table(rows, [38 * mm, 28 * mm, 28 * mm, 30 * mm, 30 * mm, 30 * mm, 35 * mm])


def _timestamp_table(
    statistics: dict[str, dict[str, Any]], style: ParagraphStyle
) -> Table:
    rows: list[list[Any]] = [
        ["Column", "Earliest", "Latest", "Invalid", "Future"]
    ]
    for column, values in statistics.items():
        rows.append(
            [
                column,
                values.get("earliest") or "—",
                values.get("latest") or "—",
                values.get("invalid_timestamp_count", 0),
                values.get("future_timestamp_count", 0),
            ]
        )
    if len(rows) == 1:
        rows.append(["No timestamp columns", "—", "—", "—", "—"])
    return _table(rows, [40 * mm, 65 * mm, 65 * mm, 25 * mm, 25 * mm])


def _categorical_table(
    statistics: dict[str, dict[str, Any]], style: ParagraphStyle
) -> Table:
    rows: list[list[Any]] = [["Column", "Distinct", "Top values"]]
    for column, values in statistics.items():
        top_values = ", ".join(
            f"{item['value']} ({item['count']})"
            for item in values.get("top_values", [])
        )
        rows.append(
            [
                column,
                values.get("distinct_value_count", 0),
                _paragraph(top_values or "—", style),
            ]
        )
    if len(rows) == 1:
        rows.append(["No categorical columns", "—", "—"])
    return _table(rows, [45 * mm, 25 * mm, 150 * mm])


def _rule_table(
    result: DatasetValidationResult, style: ParagraphStyle
) -> Table:
    rows: list[list[Any]] = [
        ["Rule ID", "Category", "Severity", "Status", "Failed", "Message"]
    ]
    for rule in result.rules:
        rows.append(
            [
                rule.rule_id,
                rule.category,
                rule.severity,
                rule.status,
                rule.failed_record_count,
                _paragraph(rule.message, style),
            ]
        )
    return _table(
        rows,
        [50 * mm, 35 * mm, 22 * mm, 24 * mm, 18 * mm, 90 * mm],
    )


def _cross_dataset_table(
    summary: dict[str, Any], style: ParagraphStyle
) -> Table:
    rows: list[list[Any]] = [
        ["Rule", "Dataset", "Category", "Status", "Failed", "Description"]
    ]
    for rule in summary["cross_dataset_rules"]:
        rows.append(
            [
                rule["rule_id"],
                rule["dataset_type"],
                rule["category"],
                rule["status"],
                rule["failed_record_count"],
                _paragraph(rule["message"], style),
            ]
        )
    if len(rows) == 1:
        rows.append(["No cross-dataset rules", "—", "—", "—", 0, "—"])
    return _table(
        rows,
        [50 * mm, 30 * mm, 38 * mm, 25 * mm, 18 * mm, 85 * mm],
    )


def _checksum_table(
    results: list[DatasetValidationResult], style: ParagraphStyle
) -> Table:
    rows: list[list[Any]] = [["Dataset", "SHA-256", "Source"]]
    for result in results:
        rows.append(
            [
                result.dataset_type,
                _paragraph(result.source_sha256, style),
                _paragraph(result.source_path, style),
            ]
        )
    return _table(rows, [35 * mm, 90 * mm, 125 * mm])


def _rule_identifier_table(
    results: list[DatasetValidationResult], style: ParagraphStyle
) -> Table:
    rows: list[list[Any]] = [["Rule ID", "Dataset", "Description"]]
    seen: set[str] = set()
    for result in results:
        for rule in result.rules:
            if rule.rule_id in seen:
                continue
            seen.add(rule.rule_id)
            rows.append(
                [
                    rule.rule_id,
                    rule.dataset_type,
                    _paragraph(rule.rule_name, style),
                ]
            )
    return _table(rows, [75 * mm, 35 * mm, 130 * mm])


def _failed_categories(result: DatasetValidationResult) -> Counter[str]:
    return Counter(
        rule.category
        for rule in result.rules
        if rule.status == "FAILED"
    )


def _recommendations(
    results: list[DatasetValidationResult],
) -> list[str]:
    categories = Counter(
        rule.category
        for result in results
        for rule in result.rules
        if rule.status in {"FAILED", "WARNING"}
    )
    recommendations: list[str] = []
    mapping = {
        "Schema": "Align source schemas with the documented required columns.",
        "Completeness": "Correct missing required values at the source; do not impute in validation.",
        "Uniqueness": "Remove duplicate records and business keys at the source.",
        "Range": "Correct out-of-range ages, ratings, quantities, scores, or timestamps.",
        "Format": "Correct malformed identifiers, UUIDs, numbers, dates, and categories.",
        "Referential Integrity": "Resolve orphan user and product references before preparation.",
        "Business Rules": "Align source events and purchases with generator business contracts.",
        "Consistency": "Reconcile prices, purchase amounts, click chronology, and popularity statistics.",
    }
    for category, recommendation in mapping.items():
        if categories[category]:
            recommendations.append(recommendation)
    return recommendations


def _table(rows: list[list[Any]], widths: list[float]) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17365D")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("LEADING", (0, 0), (-1, -1), 8.5),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F6FA")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _paragraph(value: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_escape(value), style)


def _escape(value: Any) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _page_number(canvas: Any, document: Any) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.grey)
    canvas.drawRightString(
        landscape(A4)[0] - 14 * mm,
        8 * mm,
        f"RecoMart Data Quality Report  |  Page {document.page}",
    )
    canvas.restoreState()
