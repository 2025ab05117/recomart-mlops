"""Generate the evidence-backed RecoMart PDF with the existing ReportLab stack."""
from __future__ import annotations

import argparse
import csv
import html
import json
import logging
import re
import sqlite3
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml
from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, Image, PageBreak, PageTemplate, Paragraph,
    Spacer, Table, TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT / "configs/config.yaml"
PDF = ROOT / "reports/final/RecroMart_Project_Report_v3.pdf"
META = ROOT / "reports/final/RecroMart_Project_Report_v3_metadata.json"
HEADINGS = (
    "Project Title", "Team Member Details", "Problem Statement", "Objectives",
    "Methodology / Pipeline", "Implementation Details",
    "Results and Output Screenshots", "Conclusion and Future Scope",
)
NAVY, BLUE = colors.HexColor("#17365D"), colors.HexColor("#2E75B6")
PALE, INK = colors.HexColor("#D9EAF7"), colors.HexColor("#252525")


class ReportConfigurationError(ValueError):
    """Indicate invalid report metadata."""


class ReportValidationError(RuntimeError):
    """Indicate invalid rendered output."""


@dataclass
class Evidence:
    """Repository artifacts used in one report."""

    timestamp: str
    eda_batch: str | None = None
    eda_summary: dict[str, Any] = field(default_factory=dict)
    eda_images: list[Path] = field(default_factory=list)
    screenshots: list[tuple[str, Path]] = field(default_factory=list)
    feature_db: Path | None = None
    feature_tables: list[dict[str, Any]] = field(default_factory=list)
    dvc: list[dict[str, Any]] = field(default_factory=list)
    dvc_status: str | None = None
    dvc_dag: str | None = None
    model: dict[str, Any] = field(default_factory=dict)
    mlflow_experiment: str | None = None
    mlflow_runs: list[dict[str, Any]] = field(default_factory=list)
    datasets: list[dict[str, Any]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


class AcademicReportTemplate(BaseDocTemplate):
    """Retain the existing academic page template."""

    def __init__(self, filename: str, *, report_title: str, **kwargs: Any) -> None:
        super().__init__(filename, **kwargs)
        self.report_title = report_title
        frame = Frame(
            self.leftMargin, self.bottomMargin, self.width, self.height, id="body"
        )
        self.addPageTemplates(PageTemplate(
            id="academic", frames=[frame], onPage=self._page
        ))

    def afterFlowable(self, flowable: Any) -> None:
        if isinstance(flowable, Paragraph) and flowable.style.name == "Heading1":
            key = f"section-{self.seq.nextf('section')}"
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(flowable.getPlainText(), key, level=0)
            self.notify("TOCEntry", (0, flowable.getPlainText(), self.page, key))

    def _page(self, canvas: Any, document: Any) -> None:
        canvas.saveState()
        if document.page > 1:
            canvas.setStrokeColor(PALE)
            canvas.line(18 * mm, 282 * mm, 192 * mm, 282 * mm)
            canvas.setFont("Helvetica", 8)
            canvas.setFillColor(NAVY)
            canvas.drawString(18 * mm, 285 * mm, self.report_title[:90])
            canvas.setFillColor(colors.HexColor("#666666"))
            canvas.drawString(18 * mm, 12 * mm, "RecoMart | DM4DL Assignment")
            canvas.drawRightString(192 * mm, 12 * mm, f"Page {document.page}")
        canvas.restoreState()


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TitlePage", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=25, leading=31, alignment=TA_CENTER, textColor=NAVY,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle", parent=base["Normal"], fontSize=14, leading=20,
            alignment=TA_CENTER, textColor=BLUE,
        ),
        "cover": ParagraphStyle(
            "Cover", parent=base["Normal"], fontSize=11, leading=17,
            alignment=TA_CENTER, textColor=INK,
        ),
        "h1": ParagraphStyle(
            "Heading1", parent=base["Heading1"], fontName="Helvetica-Bold",
            fontSize=17, leading=22, textColor=NAVY, spaceBefore=4 * mm,
            spaceAfter=4 * mm, keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "Heading2", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=13, leading=17, textColor=BLUE, spaceBefore=4 * mm,
            spaceAfter=2 * mm, keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "Body", parent=base["BodyText"], fontSize=11, leading=16,
            alignment=TA_JUSTIFY, textColor=INK, spaceAfter=3 * mm,
        ),
        "bullet": ParagraphStyle(
            "Bullet", parent=base["BodyText"], fontSize=10.5, leading=15,
            leftIndent=8 * mm, firstLineIndent=-4 * mm, spaceAfter=1.5 * mm,
        ),
        "caption": ParagraphStyle(
            "Caption", parent=base["BodyText"], fontSize=9, leading=12,
            alignment=TA_CENTER, textColor=colors.HexColor("#555555"),
            spaceAfter=3 * mm,
        ),
        "cell": ParagraphStyle(
            "Cell", parent=base["BodyText"], fontSize=7.5, leading=9.5,
        ),
        "small": ParagraphStyle(
            "Small", parent=base["BodyText"], fontSize=9, leading=12,
        ),
    }


def _load_metadata(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ReportConfigurationError(f"Cannot read metadata: {path}") from exc
    if not isinstance(value, dict):
        raise ReportConfigurationError("Metadata must be a mapping.")
    for key in ("report", "project"):
        if not isinstance(value.get(key), dict):
            raise ReportConfigurationError(f"{key} must be a mapping.")
    if not isinstance(value.get("team"), list) or not value["team"]:
        raise ReportConfigurationError("team must be a non-empty list.")
    for key in (
        "title", "subtitle", "institution", "assignment", "version",
        "academic_year", "generated_by",
    ):
        if not str(value["report"].get(key, "")).strip():
            raise ReportConfigurationError(f"report.{key} is required.")
    serials = []
    for member in value["team"]:
        for key in ("serial_no", "name", "bits_id"):
            if not str(member.get(key, "")).strip():
                raise ReportConfigurationError(f"team.{key} is required.")
        serials.append(int(member["serial_no"]))
    if len(serials) != len(set(serials)):
        raise ReportConfigurationError("Team serial numbers must be unique.")
    value["team"] = sorted(value["team"], key=lambda row: int(row["serial_no"]))
    return value


def _plain(text: str) -> str:
    text = re.sub(r"!\[[^]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("*", "").replace("_", "").replace(chr(96), "")
    text = re.sub(r"^\s*[>|]\s?", "", text, flags=re.MULTILINE)
    return re.sub(r"\s+", " ", text).strip()


def _md(relative: str, heading: str) -> list[str]:
    """Read a named section from existing Markdown documentation."""
    path = ROOT / relative
    if not path.exists():
        return []
    active, level, chosen, fence = False, 0, [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(chr(96) * 3):
            fence = not fence
            continue
        if fence:
            continue
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            current = len(match.group(1))
            if active and current <= level:
                break
            if _plain(match.group(2)).lower() == heading.lower():
                active, level = True, current
            continue
        if active:
            chosen.append(line)
    return [
        clean for block in re.split(r"\n\s*\n", "\n".join(chosen))
        if (clean := _plain(block))
    ]


def _documented(sources: Sequence[tuple[str, str]], limit: int = 8) -> list[str]:
    result: list[str] = []
    for path, heading in sources:
        result.extend(_md(path, heading))
    return result[:limit]


def _discover() -> Evidence:
    e = Evidence(datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z"))
    batches = []
    for path in (ROOT / "reports/eda").glob(
        "processing_date=*/processing_hour=*/batch_id=*"
    ):
        key = (
            path.parents[1].name.partition("=")[2],
            path.parent.name.partition("=")[2],
            path.name.partition("=")[2],
        )
        if all(key) and list(path.glob("*.png")):
            batches.append((*key, path))
    if batches:
        _, _, e.eda_batch, directory = max(batches)
        e.eda_images = sorted(directory.glob("*.png"))
        summary = directory / "eda_summary.json"
        if summary.exists():
            try:
                e.eda_summary = json.loads(summary.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                e.missing.append("Readable EDA summary JSON")
    else:
        e.missing.append("EDA batch and charts")

    mappings = (
        (("repository",), "Repository Structure"),
        (("clickstream",), "Clickstream Dataset"),
        (("purchase",), "Purchase History Dataset"),
        (("raw_storage", "storage_structure"), "Raw Storage Structure"),
        (("mlrun", "mlflow", "experiment"), "MLflow Results"),
        (("airflow", "dag"), "Airflow Orchestration"),
    )
    seen: set[Path] = set()
    for directory in ROOT.rglob("*screenshots*"):
        if directory.is_dir():
            for path in sorted(candidate for candidate in directory.rglob("*") if candidate.suffix.lower() in {".png", ".jpg", ".jpeg"}):
                for terms, label in mappings:
                    if path not in seen and any(x in path.name.lower() for x in terms):
                        e.screenshots.append((label, path))
                        seen.add(path)
                        break
    if not e.screenshots:
        e.missing.append("Repository screenshots")

    database = ROOT / "data/recomart_features.db"
    if database.exists():
        e.feature_db = database
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            names = [
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
            for name in names:
                safe = name.replace('"', '""')
                columns = list(connection.execute(f'PRAGMA table_info("{safe}")'))
                count = connection.execute(
                    f'SELECT COUNT(*) FROM "{safe}"'
                ).fetchone()[0]
                samples = [
                    dict(row) for row in connection.execute(
                        f'SELECT * FROM "{safe}" LIMIT 5'
                    )
                ]
                e.feature_tables.append({
                    "name": name, "rows": int(count),
                    "columns": [
                        f"{row[1]} ({row[2] or 'untyped'})" for row in columns
                    ],
                    "pk": [row[1] for row in columns if row[5]],
                    "samples": samples,
                })
        except sqlite3.Error:
            e.feature_tables.clear()
            e.missing.append("Readable feature-store schema")
        finally:
            if connection:
                connection.close()
    else:
        e.missing.append("Feature-store SQLite database")

    dvc_path = ROOT / "dvc.yaml"
    if dvc_path.exists():
        try:
            stages = (
                yaml.safe_load(dvc_path.read_text(encoding="utf-8")) or {}
            ).get("stages", {})
            for name, item in stages.items():
                e.dvc.append({
                    "stage": name, "command": item.get("cmd", ""),
                    "deps": item.get("deps", []), "outs": item.get("outs", []),
                })
        except (OSError, UnicodeError, yaml.YAMLError):
            e.missing.append("Readable dvc.yaml")
        if not (ROOT / "dvc.lock").exists():
            e.missing.append("dvc.lock")
        try:
            for command, attribute in (
                ("status", "dvc_status"), ("dag", "dvc_dag")
            ):
                result = subprocess.run(
                    ["dvc", command], cwd=ROOT, text=True, capture_output=True,
                    timeout=20, check=False,
                )
                setattr(e, attribute, (
                    result.stdout or result.stderr
                ).strip() or None)
        except (OSError, subprocess.SubprocessError):
            e.missing.append("Optional DVC CLI status and DAG output")
    else:
        e.missing.append("dvc.yaml")

    successful = []
    for path in (ROOT / "reports/model_training").glob(
        "model_run_id=*/training_summary.json"
    ):
        try:
            summary = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if summary.get("status") == "SUCCESS":
            successful.append((str(summary.get("completed_at", "")), summary))
    if successful:
        e.model = max(successful, key=lambda pair: pair[0])[1]
    else:
        e.missing.append("Successful model-training summary")

    runs: list[dict[str, Any]] = []
    for root in (ROOT / "mlruns", ROOT / "reports/mlruns"):
        if not root.exists():
            continue
        for experiment in root.iterdir():
            if not experiment.is_dir() or not experiment.name.isdigit():
                continue
            exp_name = experiment.name
            exp_meta = experiment / "meta.yaml"
            if exp_meta.exists():
                try:
                    exp_name = str((
                        yaml.safe_load(exp_meta.read_text(encoding="utf-8")) or {}
                    ).get("name", exp_name))
                except (OSError, UnicodeError, yaml.YAMLError):
                    pass
            for run_dir in experiment.iterdir():
                meta_path = run_dir / "meta.yaml"
                if not run_dir.is_dir() or not meta_path.exists():
                    continue
                try:
                    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
                except (OSError, UnicodeError, yaml.YAMLError):
                    continue
                if str(meta.get("status", "")).upper() not in {"3", "FINISHED"}:
                    continue
                metrics = {}
                for metric in (run_dir / "metrics").glob("*"):
                    try:
                        fields = metric.read_text(
                            encoding="utf-8"
                        ).strip().splitlines()[-1].split()
                        metrics[metric.name] = float(fields[1])
                    except (OSError, UnicodeError, ValueError, IndexError):
                        pass
                parameters = {}
                for parameter in (run_dir / "params").glob("*"):
                    try:
                        parameters[parameter.name] = parameter.read_text(encoding="utf-8").strip()
                    except (OSError, UnicodeError):
                        pass
                run_name = run_dir.name
                tag = run_dir / "tags/mlflow.runName"
                if tag.exists():
                    run_name = tag.read_text(encoding="utf-8").strip()
                runs.append({
                    "experiment": exp_name, "name": run_name,
                    "run_id": str(meta.get("run_id", run_dir.name)),
                    "status": "FINISHED",
                    "start": int(meta.get("start_time", 0) or 0),
                    "metrics": metrics, "parameters": parameters,
                })
    runs.sort(key=lambda row: row["start"], reverse=True)
    e.mlflow_runs = runs[:2]
    if runs:
        e.mlflow_experiment = runs[0]["experiment"]
    else:
        e.missing.append("Successful local MLflow runs")

    incoming = ROOT / "data/incoming"
    for name in (
        "users.csv", "products.json", "clickstream.csv",
        "purchasehistory.csv", "popularity.json",
    ):
        path = incoming / name
        if not path.exists():
            continue
        try:
            if path.suffix == ".csv":
                with path.open("r", encoding="utf-8", newline="") as stream:
                    reader = csv.reader(stream)
                    columns, rows = len(next(reader)), sum(1 for _ in reader)
            else:
                payload = json.loads(path.read_text(encoding="utf-8"))
                rows = len(payload) if isinstance(payload, list) else 1
                columns = len(payload[0]) if isinstance(payload, list) and payload else 0
            e.datasets.append({
                "dataset": path.stem, "rows": rows, "columns": columns,
                "location": path.relative_to(ROOT).as_posix(),
            })
        except (OSError, UnicodeError, csv.Error, json.JSONDecodeError):
            e.missing.append(f"Readable dataset summary for {name}")
    return e


def _p(text: object, style: ParagraphStyle, markup: bool = False) -> Paragraph:
    value = str(text) if markup else html.escape(str(text))
    return Paragraph(value.replace("\n", "<br/>"), style)


def _h1(number: int, title: str, s: Mapping[str, ParagraphStyle]) -> Paragraph:
    return Paragraph(f"{number}. {html.escape(title)}", s["h1"])


def _h2(number: str, title: str, s: Mapping[str, ParagraphStyle]) -> Paragraph:
    return Paragraph(f"{number} {html.escape(title)}", s["h2"])


def _table(
    rows: list[list[object]], widths: list[float],
    s: Mapping[str, ParagraphStyle],
) -> Table:
    table = Table(
        [[_p(cell, s["cell"]) for cell in row] for row in rows],
        colWidths=widths, repeatRows=1, hAlign="LEFT",
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#AAB7C4")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [
            colors.white, colors.HexColor("#F5F8FB")
        ]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _image(path: Path, caption: str, s: Mapping[str, ParagraphStyle]) -> list[Any]:
    image = Image(str(path))
    scale = min(165 * mm / image.imageWidth, 205 * mm / image.imageHeight, 1)
    image.drawWidth = image.imageWidth * scale
    image.drawHeight = image.imageHeight * scale
    image.hAlign = "CENTER"
    return [image, _p(caption, s["caption"])]


def _pipeline() -> Image:
    path = ROOT / "reports/screenshots/endtoendpipeline.png"
    if not path.is_file():
        raise ReportConfigurationError(
            "Required pipeline image not found:\n"
            "reports/screenshots/endtoendpipeline.png"
        )
    image = Image(str(path))
    scale = min(165 * mm / image.imageWidth, 190 * mm / image.imageHeight, 1)
    image.drawWidth = image.imageWidth * scale
    image.drawHeight = image.imageHeight * scale
    image.hAlign = "CENTER"
    return image

def _add_docs(
    story: list[Any], sources: Sequence[tuple[str, str]],
    s: Mapping[str, ParagraphStyle], limit: int = 8,
) -> None:
    for value in _documented(sources, limit):
        story.append(_p(value, s["body"]))


def _implementation(
    story: list[Any], e: Evidence, s: Mapping[str, ParagraphStyle],
) -> None:
    sections = (
        ("6.1", "Synthetic Data Generation", [
            ("docs/architecture/PROJECT_OVERVIEW.md", "In Scope")
        ]),
        ("6.2", "Data Ingestion", [
            ("docs/pipeline/ingestion/INGESTION_DESIGN.md", "Components"),
            ("docs/pipeline/ingestion/INGESTION_DESIGN.md", "Retry Strategy"),
            ("docs/pipeline/ingestion/INGESTION_DESIGN.md", "Manifest"),
        ]),
        ("6.3", "Storage Structure", [
            ("docs/pipeline/ingestion/RAW_STORAGE_STRUCTURE.md", "Layout"),
            ("docs/architecture/DATA_FLOW_ARCHITECTURE.md", "Data layers"),
        ]),
        ("6.4", "Data Validation and Quarantine", [
            ("docs/pipeline/validation/DATA_VALIDATION_DESIGN.md",
             "Dataset and Cross-Dataset Validation"),
            ("docs/pipeline/validation/DATA_VALIDATION_DESIGN.md",
             "Validated and Quarantine Split"),
        ]),
        ("6.5", "Data Preparation and EDA", [
            ("docs/pipeline/preparation/DATA_PREPARATION_DESIGN.md", "Cleaning"),
            ("docs/pipeline/preparation/DATA_PREPARATION_DESIGN.md",
             "Encoding and Normalization"),
            ("docs/pipeline/preparation/DATA_PREPARATION_DESIGN.md",
             "Time Features and Splitting"),
        ]),
        ("6.6", "Feature Engineering", [
            ("docs/pipeline/feature_engineering/FEATURE_ENGINEERING_DESIGN.md",
             "Feature Logic"),
            ("docs/pipeline/feature_engineering/FEATURE_CATALOG.md",
             "User Features"),
            ("docs/pipeline/feature_engineering/FEATURE_CATALOG.md",
             "Item Features"),
            ("docs/pipeline/feature_engineering/FEATURE_CATALOG.md",
             "User-Item Features"),
            ("docs/pipeline/feature_engineering/FEATURE_CATALOG.md",
             "Co-occurrence Features"),
            ("docs/pipeline/feature_engineering/FEATURE_CATALOG.md",
             "Similarity Features"),
        ]),
    )
    for number, title, sources in sections:
        story.append(_h2(number, title, s))
        _add_docs(story, sources, s, 8)

    story.append(_h2("6.7", "Feature Store", s))
    _add_docs(story, [
        ("docs/pipeline/feature_engineering/FEATURE_STORAGE_SCHEMA.md",
         "Storage model")
    ], s, 4)
    if e.feature_tables:
        rows = [["Table", "Row Count", "Columns", "Primary Key"]] + [
            [item["name"], item["rows"], ", ".join(item["columns"]),
             ", ".join(item["pk"]) or "None"]
            for item in e.feature_tables
        ]
        story.append(_table(rows, [34 * mm, 20 * mm, 88 * mm, 23 * mm], s))
        for item in sorted(
            e.feature_tables, key=lambda row: row["rows"], reverse=True
        )[:3]:
            if item["samples"]:
                story.append(_p(f"Sample rows: {item['name']}",
 s["small"]))
                keys = list(item["samples"][0])[:6]
                samples = [keys] + [
                    [str(row.get(key, ""))[:32] for key in keys]
                    for row in item["samples"]
                ]
                story.append(_table(
                    samples, [165 * mm / len(keys)] * len(keys), s
                ))
    else:
        story.append(_p("Evidence not available at report-generation time.", s["body"]))

    story.append(_h2("6.8", "Data Versioning and Lineage", s))
    _add_docs(story, [
        ("docs/pipeline/versioning/DATA_VERSIONING.md", "Purpose"),
        ("docs/pipeline/versioning/DATA_LINEAGE.md", "Transformations"),
    ], s, 6)
    if e.dvc:
        rows = [["Stage", "Command", "Dependencies", "Outputs"]] + [
            [item["stage"], item["command"], "\n".join(map(str, item["deps"])),
             "\n".join(map(str, item["outs"]))]
            for item in e.dvc
        ]
        story.append(_table(rows, [25 * mm, 52 * mm, 48 * mm, 40 * mm], s))
    if e.dvc_status:
        story.append(_p(f"DVC status: {e.dvc_status}", s["small"]))
    if e.dvc_dag:
        story.append(_p(f"DVC DAG: {e.dvc_dag}", s["small"]))

    story.append(_h2("6.9", "Model Training and Evaluation", s))
    _add_docs(story, [
        ("docs/pipeline/modeling/MODEL_TRAINING_DESIGN.md",
         "Collaborative model"),
        ("docs/pipeline/modeling/MODEL_TRAINING_DESIGN.md",
         "Content-based model"),
        ("docs/pipeline/modeling/MODEL_EVALUATION.md", "Metrics"),
    ], s, 9)
    models = e.model.get("models", {})
    if models:
        metric_keys = (
            "rmse", "mae", "precision_at_10", "recall_at_10", "map_at_10",
            "ndcg_at_10", "hit_rate_at_10", "coverage", "diversity", "novelty",
        )
        rows = [["Model", "Run ID", "Available Metrics", "Status"]]
        for name, model in models.items():
            metrics = model.get("metrics", {})
            available = ", ".join(
                f"{key}={metrics[key]:.4f}" for key in metric_keys
                if isinstance(metrics.get(key), (int, float))
            )
            rows.append([
                name,
                model.get("mlflow", {}).get(
                    "run_id", e.model.get("model_run_id", "")
                ),
                available, e.model.get("status", ""),
            ])
        story.append(_table(rows, [30 * mm, 37 * mm, 75 * mm, 23 * mm], s))

    story.append(_h2("6.10", "MLflow Experiment Tracking", s))
    _add_docs(story, [
        ("docs/pipeline/modeling/MLFLOW_GUIDE.md", "Tracking behavior"),
        ("docs/pipeline/modeling/MLFLOW_GUIDE.md", "Logged data"),
    ], s, 6)
    if e.mlflow_runs:
        rows = [["Experiment / Run", "Run ID", "Parameters", "Metrics", "Status / Start"]]
        for run in e.mlflow_runs:
            metrics = ", ".join(
                f"{key}={value:.4g}" for key, value
                in list(run["metrics"].items())[:8]
            )
            started = (
                datetime.fromtimestamp(
                    run["start"] / 1000, timezone.utc
                ).isoformat() if run["start"] else "Unknown"
            )
            rows.append([
                f"{run['experiment']} / {run['name']}", run["run_id"],
                ", ".join(f"{key}={value}" for key, value in list(run["parameters"].items())[:8]) or "No parameters",
                metrics or "No metrics", f"{run['status']}\n{started}",
            ])
        story.append(_table(rows, [32 * mm, 33 * mm, 35 * mm, 42 * mm, 23 * mm], s))
    else:
        story.append(_p("Evidence not available at report-generation time.", s["body"]))

    story.append(_h2("6.11", "Apache Airflow Orchestration", s))
    _add_docs(story, [
        ("docs/pipeline/orchestration/ORCHESTRATION_DESIGN.md", "Purpose"),
        ("docs/pipeline/orchestration/ORCHESTRATION_DESIGN.md",
         "Reliability Policy"),
    ], s, 7)
    story.append(_table([
        ["DAG", "File", "Task Sequence", "Retry Policy"],
        ["recomart_end_to_end_pipeline", "dags/recomart_end_to_end_dag.py",
         "configuration ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ generation ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ ingestion ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ validation ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ quality gate ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ "
         "preparation ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ feature store ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ versioning ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ modeling ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ lineage ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ summary",
         "Stage-specific bounded retries (0ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Å“2) and execution timeouts"],
    ], [35 * mm, 40 * mm, 65 * mm, 25 * mm], s))


def _story(meta: Mapping[str, Any], e: Evidence) -> list[Any]:
    s, report = _styles(), meta["report"]
    story: list[Any] = [
        _h1(1, "Project Title", s), Spacer(1, 22 * mm),
        _p(report["institution"], s["cover"]), Spacer(1, 18 * mm),
        _p(report["title"], s["title"]), _p(report["subtitle"], s["subtitle"]),
        Spacer(1, 18 * mm),
        _p(
            f"<b>{html.escape(report['assignment'])}</b><br/>"
            f"Report Version: {html.escape(report['version'])}<br/>"
            f"Academic Year: {html.escape(report['academic_year'])}<br/>"
            f"Generated: {e.timestamp}<br/>"
            f"Generated by: {html.escape(report['generated_by'])}",
            s["cover"], True,
        ),
        PageBreak(), _h1(2, "Team Member Details", s),
    ]
    team = [["S. No.", "Name", "BITS ID / Email ID"]] + [
        [member["serial_no"], member["name"], member["bits_id"]]
        for member in meta["team"]
    ]
    story.extend([
        _table(team, [18 * mm, 58 * mm, 89 * mm], s),
        Spacer(1, 8 * mm), _p("Table of Contents", s["subtitle"]),
    ])
    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle("TOC", fontName="Helvetica", fontSize=10, leading=15)
    ]
    story.extend([toc, PageBreak(), _h1(3, "Problem Statement", s)])
    _add_docs(story, [
        ("docs/architecture/PROJECT_OVERVIEW.md", "Purpose"),
        ("docs/architecture/SYSTEM_ARCHITECTURE.md", "Architectural Style"),
        ("docs/architecture/SYSTEM_ARCHITECTURE.md", "Boundaries and Contracts"),
        ("docs/pipeline/validation/DATA_VALIDATION_DESIGN.md", "Purpose and Scope"),
        ("docs/pipeline/modeling/MODEL_TRAINING_DESIGN.md", "Purpose"),
        ("docs/pipeline/orchestration/ORCHESTRATION_DESIGN.md", "Purpose"),
    ], s, 14)

    story.extend([PageBreak(), _h1(4, "Objectives", s)])
    for index, value in enumerate(
        _md("docs/architecture/PROJECT_OVERVIEW.md", "Objectives"), 1
    ):
        story.append(_p(f"{index}. {value}", s["bullet"]))

    story.extend([
        PageBreak(), _h1(5, "Methodology / Pipeline", s),
        _h2("5.1", "Pipeline Flow", s), _pipeline(),
        _p("Figure 1. RecoMart pipeline flow derived from repository architecture.",
           s["caption"]),
    ])
    for number, title, sources in (
        ("5.2", "Data Sources", [
            ("docs/pipeline/ingestion/INGESTION_DESIGN.md", "Purpose and Scope")
        ]),
        ("5.3", "Storage Zones", [
            ("docs/architecture/DATA_FLOW_ARCHITECTURE.md", "Data layers")
        ]),
        ("5.4", "Execution Flow", [
            ("docs/pipeline/orchestration/ORCHESTRATION_DESIGN.md",
             "Invocation Strategy")
        ]),
    ):
        story.append(_h2(number, title, s))
        _add_docs(story, sources, s, 5)

    story.extend([PageBreak(), _h1(6, "Implementation Details", s)])
    _implementation(story, e, s)

    story.extend([
        PageBreak(), _h1(7, "Results and Output Screenshots", s),
        _h2("7.1", "Dataset Summary", s),
    ])
    if e.datasets:
        rows = [["Dataset", "Rows", "Columns", "Location"]] + [
            [row["dataset"], row["rows"], row["columns"], row["location"]]
            for row in e.datasets
        ]
        story.append(_table(rows, [40 * mm, 25 * mm, 25 * mm, 75 * mm], s))
    else:
        story.append(_p("Evidence not available at report-generation time.", s["body"]))

    store = (
        e.feature_db.relative_to(ROOT).as_posix()
        if e.feature_db else "Not available"
    )
    story.extend([
        _h2("7.2", "Pipeline Evidence", s),
        _table([
            ["Stage", "Evidence", "Status"],
            ["EDA", e.eda_batch or "Not available",
             "Available" if e.eda_images else "Missing"],
            ["Feature Store", store,
             "Available" if e.feature_tables else "Missing"],
            ["DVC", f"{len(e.dvc)} stages in dvc.yaml",
             "Available" if e.dvc else "Missing"],
            ["Modeling", e.model.get("model_run_id", "Not available"),
             e.model.get("status", "Missing")],
            ["MLflow", f"{len(e.mlflow_runs)} selected successful runs",
             "Available" if e.mlflow_runs else "Missing"],
            ["Screenshots", f"{len(e.screenshots)} matched images",
             "Available" if e.screenshots else "Missing"],
        ], [38 * mm, 92 * mm, 35 * mm], s),
        _h2("7.3", "Repository Screenshots", s),
    ])
    for label, path in e.screenshots:
        story.append(PageBreak())
        story.extend(_image(path, f"{label} ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â {path.name}", s))

    story.append(_h2("7.4", "Latest Exploratory Data Analysis", s))
    if e.eda_batch:
        story.append(_p(
            f"Selected latest partitioned EDA batch: {e.eda_batch}.", s["body"]
        ))
    if e.eda_summary:
        summary = e.eda_summary
        story.append(_table([
            ["Measure", "Value"], ["Users", summary.get("users")],
            ["Products", summary.get("products")],
            ["Interactions", summary.get("interactions")],
            ["Density", summary.get("density")],
            ["Sparsity", summary.get("sparsity")],
            ["Train / validation / test",
             f"{summary.get('train_records')} / "
             f"{summary.get('validation_records')} / "
             f"{summary.get('test_records')}"],
        ], [75 * mm, 90 * mm], s))
    for path in e.eda_images:
        story.append(PageBreak())
        caption = path.stem.replace("_", " ").title()
        story.extend(_image(path, f"{caption} ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â EDA batch {e.eda_batch}", s))
    if not e.eda_images:
        story.append(_p("Evidence not available at report-generation time.", s["body"]))

    story.extend([
        PageBreak(), _h1(8, "Conclusion and Future Scope", s),
        _h2("8.1", "Conclusion", s),
    ])
    _add_docs(story, [
        ("docs/architecture/PROJECT_OVERVIEW.md", "Definition of Done"),
        ("docs/architecture/PROJECT_OVERVIEW.md", "Quality Attributes"),
    ], s, 9)
    for value in (
        "End-to-End Automated Pipeline", "Data Validation and Quarantine",
        "Data Preparation and EDA", "Recommendation Feature Engineering",
        "Structured Feature Store", "DVC Data Versioning and Lineage",
        "Collaborative and Content-Based Models", "MLflow Experiment Tracking",
        "Apache Airflow Orchestration", "Reproducible and Traceable Execution",
    ):
        story.append(_p(value, s["bullet"]))
    for _, path in [
        item for item in e.screenshots if "conclusion" in item[1].name.lower()
    ]:
        story.extend(_image(path, f"Conclusion ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â {path.name}", s))

    story.extend([
        _h2("8.2", "Future Scope", s),
        _p(
            "The following items are future enhancements and are not claimed "
            "as completed functionality:", s["body"]
        ),
    ])
    for value in (
        "Kafka-based real-time ingestion", "Cloud object storage",
        "Online feature serving", "Model registry and model promotion",
        "Automated retraining", "Data-drift monitoring", "Model-drift monitoring",
        "Recommendation API deployment", "A/B testing", "CI/CD integration",
        "Kubernetes deployment", "Production secrets management",
        "Access control and monitoring",
    ):
        story.append(_p(value, s["bullet"]))
    return story


def _validate(
    path: Path, meta: Mapping[str, Any], e: Evidence, pages: int
) -> int:
    if not path.exists() or path.stat().st_size == 0:
        raise ReportValidationError("PDF is missing or empty.")
    if pages < 10 and e.eda_images:
        raise ReportValidationError(f"Expected at least 10 pages; found {pages}.")
    for member in meta["team"]:
        if not str(member["name"]).strip() or not str(member["bits_id"]).strip():
            raise ReportValidationError(f"Missing team member {member['name']}.")
    if len(HEADINGS) != 8 or len(set(HEADINGS)) != 8:
        raise ReportValidationError("Top-level heading structure is invalid.")
    configured = json.dumps(meta, ensure_ascii=False)
    if "{{" in configured or "}}" in configured or "<PLACEHOLDER>" in configured:
        raise ReportValidationError("Unresolved template marker found.")
    if e.eda_images and not e.eda_batch:
        raise ReportValidationError("EDA batch is not identified.")
    for image in [*e.eda_images, *(path for _, path in e.screenshots)]:
        if not image.exists() or image.stat().st_size == 0:
            raise ReportValidationError(f"Included image unavailable: {image}")
    return pages

def generate_report(
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> tuple[Path, Path]:
    """Generate version two without overwriting earlier report artifacts."""
    for output in (PDF, META):
        if output.exists():
            raise FileExistsError(f"Refusing to overwrite existing output: {output}")
    metadata, evidence = _load_metadata(config_path.resolve()), _discover()
    PDF.parent.mkdir(parents=True, exist_ok=True)
    document = AcademicReportTemplate(
        str(PDF), report_title=metadata["report"]["title"],
        pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=20 * mm, bottomMargin=19 * mm,
        title=metadata["report"]["title"],
        author=metadata["report"]["generated_by"],
        subject=metadata["report"]["subtitle"],
    )
    try:
        story = _story(metadata, evidence)
        actual_headings = [
            item.getPlainText() for item in story
            if isinstance(item, Paragraph) and item.style.name == "Heading1"
        ]
        expected_headings = [
            f"{number}. {heading}"
            for number, heading in enumerate(HEADINGS, 1)
        ]
        if actual_headings != expected_headings:
            raise ReportValidationError(
                "Report must contain exactly the eight required top-level headings."
            )
        document.multiBuild(story)
        pages = _validate(PDF, metadata, evidence, document.page)
        result = {
            "generation_timestamp": evidence.timestamp,
            "selected_eda_batch": evidence.eda_batch,
            "mlflow_experiment": evidence.mlflow_experiment,
            "selected_mlflow_runs": [
                run["run_id"] for run in evidence.mlflow_runs
            ],
            "feature_store_database_path": (
                evidence.feature_db.relative_to(ROOT).as_posix()
                if evidence.feature_db else None
            ),
            "feature_store_tables": [
                table["name"] for table in evidence.feature_tables
            ],
            "screenshots_included": [
                path.relative_to(ROOT).as_posix()
                for _, path in evidence.screenshots
            ],
            "dvc_stages_included": [stage["stage"] for stage in evidence.dvc],
            "eda_images_included": [
                path.name for path in evidence.eda_images
            ],
            "missing_evidence": evidence.missing,
            "page_count": pages,
            "pdf_file_size": PDF.stat().st_size,
            "validation": "PASSED",
        }
        META.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception:
        PDF.unlink(missing_ok=True)
        META.unlink(missing_ok=True)
        raise
    LOGGER.info(
        "RecoMart project report generated",
        extra={"event": "project_report_generated", "output": str(PDF)},
    )
    return PDF, META


def main(argv: Sequence[str] | None = None) -> int:
    """Run the existing report generator."""
    parser = argparse.ArgumentParser(
        description="Generate the RecoMart project PDF report."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s %(message)s"
    )
    configured = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
    if configured.get("report", {}).get("versioning"):
        from src.reporting.generate_project_report_docx import generate
        output, evidence = generate(args.config)
        print(json.dumps({"output": str(output), **evidence}, indent=2))
    else:
        generate_report(args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
