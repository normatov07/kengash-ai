"""`harness skills lint|install` (SP4 spec §4)."""

from pathlib import Path

from typer.testing import CliRunner

from super_harness.cli import app

runner = CliRunner()


def test_cli_lint_is_clean_on_the_repo() -> None:
    result = runner.invoke(app, ["skills", "lint"])
    assert (result.exit_code, result.stdout) == (0, ""), result.output


def test_cli_lint_names_an_unknown_command(tmp_path: Path) -> None:
    folder = tmp_path / "typo"
    folder.mkdir()
    (folder / "SKILL.md").write_text(
        "---\nname: typo\ndescription: Use when testing.\n---\n"
        "0. Run `harness --version`.\n1. Run `harness plan reveiw <id>`.\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["skills", "lint", str(folder)])
    assert result.exit_code == 1
    assert result.stdout == f"{folder / 'SKILL.md'}: unknown command: harness plan reveiw\n"
