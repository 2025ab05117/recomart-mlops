"""Focused external-link behavior test for the documentation validator."""

from pathlib import Path

from scripts.validate_docs import validate_link


def test_mailto_external_link_is_ignored(tmp_path: Path) -> None:
    source = tmp_path / "docs" / "README.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Documentation\n", encoding="utf-8")
    assert validate_link(source, "mailto:docs@example.com", tmp_path) is None
