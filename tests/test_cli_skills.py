"""`harness skills lint|install` (SP4 spec §4)."""

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from super_harness.cli import app
from super_harness.ops import skills
from super_harness.store import StorePaths

runner = CliRunner()
UV = shutil.which("uv")  # found before the fake-CLI fixture narrows PATH


def test_cli_lint_is_clean_on_the_repo(store_paths: StorePaths) -> None:  # no real store
    result = runner.invoke(app, ["skills", "lint"])
    assert (result.exit_code, result.stdout) == (0, ""), result.output


def test_cli_lint_names_an_unknown_command(tmp_path: Path, store_paths: StorePaths) -> None:
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


def test_cli_install_exits_5_until_yes(
    tmp_path: Path, store_paths: StorePaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source" / "alpha"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("---\nname: alpha\ndescription: Use when.\n---\nv1\n")
    monkeypatch.setattr(skills, "packaged", lambda: tmp_path / "source")
    repo = tmp_path / "repo"
    repo.mkdir()
    first = runner.invoke(app, ["skills", "install", "--agent", "claude", "--path", str(repo)])
    folder = repo / ".claude" / "skills" / "alpha"
    assert (first.exit_code, first.stdout) == (0, f"claude alpha: installed → {folder}\n")
    (folder / "SKILL.md").write_text("---\nname: alpha\ndescription: Use when.\n---\nmine\n")
    held = runner.invoke(app, ["skills", "install", "--agent", "claude", "--path", str(repo)])
    assert held.exit_code == 5 and "-mine\n+v1\n" in held.stdout
    assert "rerun with --yes" in held.stderr
    done = runner.invoke(
        app, ["skills", "install", "--agent", "claude", "--path", str(repo), "--yes"]
    )
    assert done.exit_code == 0 and done.stdout == f"claude alpha: updated → {folder}\n"


@pytest.mark.skipif(UV is None, reason="uv is not installed")
def test_the_wheel_carries_skills_and_roles(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    build = [str(UV), "build", "--wheel", "--quiet", "-o", str(tmp_path)]
    subprocess.run(build, cwd=root, check=True)
    (wheel,) = tmp_path.glob("*.whl")
    names = set(zipfile.ZipFile(wheel).namelist())
    assert {"super_harness/skills/README.md", "super_harness/roles/plan/SKILL.md"} <= names
