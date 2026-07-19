"""Tests for the repository documentation validator."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.validate_docs import (
    MANDATORY_DOCUMENTS,
    extract_markdown_links,
    validate_link,
    validate_repository,
)


def write(path: Path, content: str = "# Document\n") -> Path:
    """Create a UTF-8 fixture file and return its path."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def create_minimum_docs(root: Path) -> None:
    """Create the mandatory indexed documentation fixture."""

    for relative in MANDATORY_DOCUMENTS:
        write(root / relative)
    sections = ("instructions", "architecture", "standards", "pipeline", "operations")
    links = "\n".join(f"- [{name}]({name}/README.md)" for name in sections)
    write(root / "docs/README.md", f"# Documentation\n\n{links}\n")


def test_valid_relative_markdown_link(tmp_path: Path) -> None:
    source = write(tmp_path / "docs/a/README.md", "[Target](../b/TARGET.md)")
    write(tmp_path / "docs/b/TARGET.md")
    assert validate_link(source, "../b/TARGET.md", tmp_path) is None


def test_broken_relative_markdown_link(tmp_path: Path) -> None:
    source = write(tmp_path / "docs/README.md", "[Missing](missing.md)")
    assert validate_link(source, "missing.md", tmp_path) is not None


def test_anchor_and_external_link_handling(tmp_path: Path) -> None:
    source = write(tmp_path / "docs/README.md", "# Home\n\n## Valid Section\n")
    assert validate_link(source, "#valid-section", tmp_path) is None
    assert validate_link(source, "#missing-section", tmp_path) is not None
    assert validate_link(source, "https://example.com/docs", tmp_path) is None


def test_image_link_handling(tmp_path: Path) -> None:
    source = write(tmp_path / "docs/README.md", "![Graph](images/graph.png)")
    write(tmp_path / "docs/images/graph.png", "not-a-real-image")
    target = extract_markdown_links(source.read_text(encoding="utf-8"))[0]
    assert validate_link(source, target, tmp_path) is None


def test_missing_subfolder_readme(tmp_path: Path) -> None:
    create_minimum_docs(tmp_path)
    write(tmp_path / "docs/orphan/DESIGN.md")
    result = validate_repository(tmp_path)
    assert any("lacks README.md" in error for error in result.errors)


def test_missing_mandatory_document(tmp_path: Path) -> None:
    create_minimum_docs(tmp_path)
    (tmp_path / MANDATORY_DOCUMENTS[-1]).unlink()
    result = validate_repository(tmp_path)
    assert any("Missing mandatory document" in error for error in result.errors)


def test_old_documentation_path_detection(tmp_path: Path) -> None:
    create_minimum_docs(tmp_path)
    write(tmp_path / "NOTES.md", "See docs/CODING_INSTRUCTIONS.md.")
    result = validate_repository(tmp_path)
    assert any("stale documentation path" in error for error in result.errors)


def test_duplicate_filename_reporting(tmp_path: Path) -> None:
    create_minimum_docs(tmp_path)
    write(tmp_path / "docs/a/README.md")
    write(tmp_path / "docs/a/SCHEMA.md")
    write(tmp_path / "docs/b/README.md")
    write(tmp_path / "docs/b/SCHEMA.md")
    result = validate_repository(tmp_path)
    assert any("Duplicate filename schema.md" in item for item in result.warnings)


def test_reorganized_repository_documentation_is_valid() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    result = validate_repository(repository_root)
    assert result.errors == []
