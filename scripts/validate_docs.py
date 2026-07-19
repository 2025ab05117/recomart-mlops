"""Validate RecoMart documentation structure and local Markdown references."""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

MARKDOWN_LINK_PATTERN = re.compile(
    r"!?\[[^\]]*\]\(\s*(?:<([^>]+)>|([^) \t]+))(?:\s+['\"][^'\"]*['\"])?\s*\)"
)
HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
EXTERNAL_SCHEMES = ("http://", "https://", "mailto:", "tel:", "data:")
TEXT_SUFFIXES = {
    ".md", ".py", ".ipynb", ".yaml", ".yml", ".ps1", ".sh", ".sql",
    ".toml", ".ini", ".cfg", ".txt",
}
EXCLUDED_PARTS = {
    ".git", ".venv", "__pycache__", ".pytest_cache", "data", "logs",
    "mlruns", "models", "reports",
}
MANDATORY_DOCUMENTS = (
    "docs/README.md",
    "docs/instructions/CODEX_INSTRUCTIONS.md",
    "docs/architecture/SYSTEM_ARCHITECTURE.md",
    "docs/standards/DEVELOPMENT_GUIDE.md",
    "docs/standards/CODING_STANDARDS.md",
    "docs/pipeline/README.md",
    "docs/operations/END_TO_END_EXECUTION_GUIDE.md",
)
OLD_DOCUMENT_PATHS = (
    "docs/00_Project_Overview.md",
    "docs/01_Project_Structure.md",
    "docs/02_System_Architecture.md",
    "docs/03_Data_Flow.md",
    "docs/04_S3_Data_Lake.md",
    "docs/05_Database_Design.md",
    "docs/06_Coding_Standards.md",
    "docs/07_Airflow_Guidelines.md",
    "docs/08_Feature_Engineering.md",
    "docs/09_Modeling_Guidelines.md",
    "docs/10_Reporting_Guidelines.md",
    "docs/11_Project_Rules.md",
    "docs/CODING_INSTRUCTIONS.md",
    "docs/INGESTION_DESIGN.md",
    "docs/DATA_VALIDATION_DESIGN.md",
    "docs/DATA_PREPARATION_DESIGN.md",
    "docs/FEATURE_ENGINEERING_DESIGN.md",
    "docs/DATA_VERSIONING.md",
    "docs/MODEL_TRAINING_DESIGN.md",
    "docs/ORCHESTRATION_DESIGN.md",
)


@dataclass(slots=True)
class ValidationResult:
    """Collect documentation validation errors, warnings, and counts."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    markdown_files: int = 0
    links_checked: int = 0

    @property
    def is_valid(self) -> bool:
        """Return whether no validation error was found."""

        return not self.errors


def extract_markdown_links(text: str) -> list[str]:
    """Return Markdown link and image targets found in text."""

    return [
        (match.group(1) or match.group(2)).strip()
        for match in MARKDOWN_LINK_PATTERN.finditer(text)
    ]


def github_anchor(value: str) -> str:
    """Return a practical GitHub-compatible anchor slug for a heading."""

    value = re.sub(r"[^\w\s-]", "", value.strip().lower(), flags=re.UNICODE)
    return re.sub(r"[\s-]+", "-", value).strip("-")


def markdown_anchors(path: Path) -> set[str]:
    """Return anchors declared by Markdown headings in ``path``."""

    text = path.read_text(encoding="utf-8")
    counts: dict[str, int] = defaultdict(int)
    anchors: set[str] = set()
    for heading in HEADING_PATTERN.findall(text):
        base = github_anchor(re.sub(r"`([^`]*)`", r"\1", heading))
        if not base:
            continue
        suffix = counts[base]
        anchors.add(base if suffix == 0 else f"{base}-{suffix}")
        counts[base] += 1
    return anchors


def _is_external(target: str) -> bool:
    return target.lower().startswith(EXTERNAL_SCHEMES) or target.startswith("//")


def validate_link(source: Path, target: str, repository_root: Path) -> str | None:
    """Validate one local Markdown link and return an error when invalid."""

    target = unquote(target.replace("\\", "/"))
    if not target or _is_external(target):
        return None
    path_text, separator, anchor = target.partition("#")
    if path_text:
        candidate = (
            repository_root / path_text.lstrip("/")
            if path_text.startswith("/")
            else source.parent / path_text
        ).resolve()
    else:
        candidate = source.resolve()
    if not candidate.exists():
        return f"{source}: linked path does not exist: {target}"
    if separator and anchor and candidate.suffix.lower() == ".md":
        if github_anchor(anchor) not in markdown_anchors(candidate):
            return f"{source}: linked anchor does not exist: {target}"
    return None


def _iter_repository_text_files(repository_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in repository_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        parts = path.relative_to(repository_root).parts
        if any(part in EXCLUDED_PARTS for part in parts):
            continue
        if any(part.startswith(".") and part != ".github" for part in parts):
            continue
        if path == Path(__file__).resolve():
            continue
        if "tests" in parts and path.name == "test_validate_docs.py":
            continue
        files.append(path)
    return files


def validate_repository(repository_root: Path) -> ValidationResult:
    """Validate documentation beneath ``repository_root``."""

    root = repository_root.resolve()
    docs_root = root / "docs"
    result = ValidationResult()

    for relative in MANDATORY_DOCUMENTS:
        if not (root / relative).is_file():
            result.errors.append(f"Missing mandatory document: {relative}")

    markdown_files = sorted(docs_root.rglob("*.md")) if docs_root.exists() else []
    result.markdown_files = len(markdown_files)
    for path in markdown_files:
        if not path.read_text(encoding="utf-8").strip():
            result.errors.append(f"Empty Markdown file: {path.relative_to(root)}")

    for directory in sorted(path for path in docs_root.rglob("*") if path.is_dir()):
        if any(directory.glob("*.md")) and not (directory / "README.md").is_file():
            result.errors.append(
                "Populated documentation folder lacks README.md: "
                f"{directory.relative_to(root)}"
            )

    duplicate_names: dict[str, list[Path]] = defaultdict(list)
    for path in markdown_files:
        if path.name != "README.md":
            duplicate_names[path.name.lower()].append(path)
    for name, paths in sorted(duplicate_names.items()):
        if len(paths) > 1:
            locations = ", ".join(str(path.relative_to(root)) for path in paths)
            result.warnings.append(f"Duplicate filename {name}: {locations}")

    for source in _iter_repository_text_files(root):
        try:
            text = source.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        normalized = text.replace("\\", "/")
        for old_path in OLD_DOCUMENT_PATHS:
            if old_path in normalized:
                result.errors.append(
                    f"{source.relative_to(root)}: stale documentation path: {old_path}"
                )
        for target in extract_markdown_links(text):
            if (
                source.suffix.lower() != ".md"
                and ".md" not in target.lower()
                and "docs/" not in target.replace("\\", "/").lower()
            ):
                continue
            result.links_checked += 1
            error = validate_link(source, target, root)
            if error:
                result.errors.append(error.replace("\\", "/"))

    root_index = docs_root / "README.md"
    if root_index.is_file():
        root_targets = {
            target.partition("#")[0].replace("\\", "/")
            for target in extract_markdown_links(root_index.read_text(encoding="utf-8"))
        }
        for section in sorted(path for path in docs_root.iterdir() if path.is_dir()):
            if any(section.rglob("*.md")):
                expected = f"{section.name}/README.md"
                if expected not in root_targets:
                    result.errors.append(
                        f"docs/README.md does not link populated section: {expected}"
                    )

    return result


def main(argv: list[str] | None = None) -> int:
    """Run documentation validation and return a process exit code."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root (default: inferred from this script).",
    )
    args = parser.parse_args(argv)
    result = validate_repository(args.root)
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    for error in result.errors:
        print(f"ERROR: {error}")
    print(
        "Documentation validation "
        f"{'PASSED' if result.is_valid else 'FAILED'}: "
        f"{result.markdown_files} Markdown files, "
        f"{result.links_checked} links inspected, "
        f"{len(result.warnings)} warnings, {len(result.errors)} errors."
    )
    return 0 if result.is_valid else 1


if __name__ == "__main__":
    sys.exit(main())
