from pathlib import Path

import pytest

from scripts.check_md_caps import main, violations


def write_lines(path: Path, count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("line\n" * count, encoding="utf-8")


def test_files_within_caps_pass_silently(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_lines(tmp_path / "AGENTS.md", 100)
    write_lines(tmp_path / "docs" / "topic.md", 150)
    assert main([str(tmp_path)]) == 0
    assert capsys.readouterr().out == ""


def test_oversized_agents_md_is_reported(tmp_path: Path) -> None:
    write_lines(tmp_path / "AGENTS.md", 101)
    assert violations(tmp_path) == ["AGENTS.md: 101 lines > cap 100"]


def test_oversized_nested_doc_is_reported(tmp_path: Path) -> None:
    write_lines(tmp_path / "docs" / "modules" / "cli" / "README.md", 151)
    assert violations(tmp_path) == ["docs/modules/cli/README.md: 151 lines > cap 150"]


def test_specs_and_plans_are_exempt(tmp_path: Path) -> None:
    write_lines(tmp_path / "docs" / "superpowers" / "specs" / "design.md", 900)
    assert violations(tmp_path) == []


def test_main_prints_each_violation_and_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_lines(tmp_path / "AGENTS.md", 120)
    assert main([str(tmp_path)]) == 1
    assert capsys.readouterr().out == "AGENTS.md: 120 lines > cap 100\n"
