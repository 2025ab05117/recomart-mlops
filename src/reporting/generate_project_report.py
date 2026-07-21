"""Generate a clean YAML-authored RecoMart academic PDF."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph, Spacer,
    Table, TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "reporting.yaml"
NAVY = colors.HexColor("#17365D")
PALE_BLUE = colors.HexColor("#D9E5F2")
BODY_COLOR = colors.HexColor("#252525")


class ReportConfigurationError(ValueError):
    """Indicate invalid or incomplete reporting configuration."""


class AcademicReportTemplate(BaseDocTemplate):
    """Render academic page furniture and table-of-contents entries."""

    def __init__(self, filename: str, *, report_title: str, **kwargs: Any) -> None:
        """Initialize the A4 document with one body frame."""
        super().__init__(filename, **kwargs)
        self.report_title = report_title
        frame = Frame(
            self.leftMargin, self.bottomMargin, self.width, self.height,
            id="report_body",
        )
        self.addPageTemplates(
            PageTemplate(id="academic", frames=[frame], onPage=self._draw_page)
        )

    def afterFlowable(self, flowable: Any) -> None:
        """Register first-level headings in the outline and contents."""
        if isinstance(flowable, Paragraph) and flowable.style.name == "Heading1":
            key = f"section-{self.seq.nextf('section')}"
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(flowable.getPlainText(), key, level=0)
            self.notify("TOCEntry", (0, flowable.getPlainText(), self.page, key))

    def _draw_page(self, canvas: Any, document: Any) -> None:
        canvas.saveState()
        if document.page > 1:
            canvas.setStrokeColor(PALE_BLUE)
            canvas.line(22 * mm, 282 * mm, 188 * mm, 282 * mm)
            canvas.setFillColor(NAVY)
            canvas.setFont("Helvetica", 8)
            canvas.drawString(22 * mm, 285 * mm, self.report_title[:86])
            canvas.setFillColor(colors.HexColor("#555555"))
            canvas.drawRightString(188 * mm, 14 * mm, f"Page {document.page}")
        canvas.restoreState()


def _mapping(config: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = config.get(key)
    if not isinstance(value, dict):
        raise ReportConfigurationError(f"{key} must be a mapping.")
    return value


def _read_config(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as stream:
            loaded = yaml.safe_load(stream)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ReportConfigurationError(f"Unable to read configuration: {path}") from exc
    if not isinstance(loaded, dict):
        raise ReportConfigurationError("Report configuration must be a mapping.")
    _mapping(loaded, "report")
    _mapping(loaded, "institution")
    for key in ("team_members", "abstract", "sections", "references"):
        if not isinstance(loaded.get(key), list) or not loaded[key]:
            raise ReportConfigurationError(f"{key} must be a non-empty list.")
    return loaded


def _styles() -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ReportTitle", parent=sample["Title"], fontName="Helvetica-Bold",
            fontSize=23, leading=29, textColor=NAVY, alignment=TA_CENTER,
            spaceAfter=8 * mm,
        ),
        "subtitle": ParagraphStyle(
            "ReportSubtitle", parent=sample["Normal"], fontSize=12, leading=17,
            alignment=TA_CENTER, textColor=colors.HexColor("#4B5563"),
        ),
        "cover": ParagraphStyle(
            "CoverText", parent=sample["Normal"], fontSize=10, leading=15,
            alignment=TA_CENTER, textColor=BODY_COLOR,
        ),
        "heading1": ParagraphStyle(
            "Heading1", parent=sample["Heading1"], fontName="Helvetica-Bold",
            fontSize=16, leading=20, textColor=NAVY, spaceBefore=4 * mm,
            spaceAfter=3 * mm, keepWithNext=True,
        ),
        "heading2": ParagraphStyle(
            "Heading2", parent=sample["Heading2"], fontName="Helvetica-Bold",
            fontSize=12, leading=15, textColor=colors.HexColor("#294E75"),
            spaceBefore=3 * mm, spaceAfter=2 * mm, keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "ReportBody", parent=sample["BodyText"], fontSize=10, leading=15,
            alignment=TA_JUSTIFY, textColor=BODY_COLOR, spaceAfter=3 * mm,
        ),
        "bullet": ParagraphStyle(
            "ReportBullet", parent=sample["BodyText"], fontSize=10, leading=14,
            leftIndent=7 * mm, firstLineIndent=-3 * mm, bulletIndent=2 * mm,
            spaceAfter=1.5 * mm,
        ),
        "small": ParagraphStyle(
            "SmallText", parent=sample["BodyText"], fontSize=8.5, leading=12,
            textColor=colors.HexColor("#555555"),
        ),
    }


def _text_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ReportConfigurationError(f"{field} must contain non-empty text.")
    return value


def _story(config: Mapping[str, Any]) -> list[Any]:
    report = _mapping(config, "report")
    institution = _mapping(config, "institution")
    styles = _styles()
    story: list[Any] = [
        Spacer(1, 20 * mm),
        Paragraph(str(institution.get("name", "")), styles["cover"]),
        Spacer(1, 18 * mm),
        Paragraph(str(report.get("title", "")), styles["title"]),
        Paragraph(str(report.get("subtitle", "")), styles["subtitle"]),
        Spacer(1, 15 * mm),
        Paragraph(
            f"<b>Course:</b> {institution.get('course', '')}<br/>"
            f"<b>Academic term:</b> {institution.get('academic_term', '')}<br/>"
            f"<b>Report version:</b> {report.get('version', '')}<br/>"
            f"<b>Submission date:</b> {report.get('submission_date', '')}",
            styles["cover"],
        ),
        Spacer(1, 12 * mm),
        Paragraph("<b>Team Members</b>", styles["subtitle"]),
        Spacer(1, 3 * mm),
    ]
    rows: list[list[Any]] = [["Name", "Student ID", "Contribution"]]
    for member in config["team_members"]:
        if not isinstance(member, dict):
            raise ReportConfigurationError("Each team member must be a mapping.")
        rows.append([
            Paragraph(str(member.get("name", "")), styles["small"]),
            Paragraph(str(member.get("student_id", "")), styles["small"]),
            Paragraph(str(member.get("contribution", "")), styles["small"]),
        ])
    team_table = Table(rows, colWidths=[42 * mm, 35 * mm, 83 * mm])
    team_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#AAB7C4")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F8FB")]),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([team_table, PageBreak(), Paragraph("Abstract", styles["heading1"])])
    story.extend(Paragraph(text, styles["body"]) for text in _text_list(config["abstract"], "abstract"))
    story.extend([PageBreak(), Paragraph("Table of Contents", styles["heading1"])])
    toc = TableOfContents()
    toc.levelStyles = [ParagraphStyle(
        "TOCLevel1", fontName="Helvetica", fontSize=10, leading=16,
        textColor=BODY_COLOR,
    )]
    story.extend([toc, PageBreak()])
    for number, section in enumerate(config["sections"], 1):
        if not isinstance(section, dict) or not str(section.get("title", "")).strip():
            raise ReportConfigurationError("Each section requires a title.")
        story.append(Paragraph(f"{number}. {section['title']}", styles["heading1"]))
        for text in _text_list(section.get("paragraphs", []), "section paragraphs"):
            story.append(Paragraph(text, styles["body"]))
        bullets = section.get("bullets", [])
        if not isinstance(bullets, list):
            raise ReportConfigurationError("Section bullets must be a list.")
        for bullet in bullets:
            story.append(Paragraph(str(bullet), styles["bullet"], bulletText="•"))
        subsections = section.get("subsections", [])
        if not isinstance(subsections, list):
            raise ReportConfigurationError("Subsections must be a list.")
        for subsection in subsections:
            if not isinstance(subsection, dict):
                raise ReportConfigurationError("Each subsection must be a mapping.")
            story.append(Paragraph(str(subsection.get("title", "")), styles["heading2"]))
            for text in _text_list(subsection.get("paragraphs", []), "subsection paragraphs"):
                story.append(Paragraph(text, styles["body"]))
    story.append(Paragraph("References", styles["heading1"]))
    for index, reference in enumerate(config["references"], 1):
        story.extend([
            Paragraph(f"[{index}] {reference}", styles["small"]),
            Spacer(1, 1.5 * mm),
        ])
    return story


def generate_report(config_path: Path = DEFAULT_CONFIG_PATH) -> Path:
    """Render a new PDF from YAML without overwriting an existing artifact."""
    config = _read_config(config_path.resolve())
    report = _mapping(config, "report")
    output_value = report.get("output_path")
    if not isinstance(output_value, str) or not output_value.strip():
        raise ReportConfigurationError("report.output_path is required.")
    relative_output = Path(output_value)
    if relative_output.is_absolute() or relative_output.suffix.lower() != ".pdf":
        raise ReportConfigurationError("output_path must be a relative PDF path.")
    output_path = (PROJECT_ROOT / relative_output).resolve()
    if PROJECT_ROOT not in output_path.parents:
        raise ReportConfigurationError("output_path must remain inside the project.")
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing PDF: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document = AcademicReportTemplate(
        str(output_path),
        report_title=str(report.get("title", "RecoMart Project Report")),
        pagesize=A4, rightMargin=22 * mm, leftMargin=22 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
        title=str(report.get("title", "RecoMart Project Report")),
        author=str(report.get("author", "RecoMart Project Team")),
        subject=str(report.get("subtitle", "Academic project report")),
    )
    try:
        document.multiBuild(_story(config))
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    LOGGER.info(
        "Project report generated",
        extra={"event": "project_report_generated", "output_path": str(output_path)},
    )
    return output_path


def main(argv: Sequence[str] | None = None) -> int:
    """Run the report generator command-line interface."""
    parser = argparse.ArgumentParser(description="Generate the static RecoMart academic PDF.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    generate_report(args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
