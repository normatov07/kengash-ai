"""`kengash skills lint|install` (SP4 spec §4)."""

import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from conftest import FakeClis
from typer.testing import CliRunner

from kengash_ai.cli import app
from kengash_ai.ops import skills
from kengash_ai.store import StorePaths

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
        "0. Run `kengash --version`.\n1. Run `kengash plan reveiw <id>`.\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["skills", "lint", str(folder)])
    assert result.exit_code == 1
    assert result.stdout == f"{folder / 'SKILL.md'}: unknown command: kengash plan reveiw\n"


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
    folder = repo / ".claude" / "skills" / "kengash" / "skills" / "alpha"
    note = "note: " + skills.TRUST_NOTE
    assert (first.exit_code, first.stdout) == (0, f"claude alpha: installed → {folder}\n{note}\n")
    (folder / "SKILL.md").write_text("---\nname: alpha\ndescription: Use when.\n---\nmine\n")
    held = runner.invoke(app, ["skills", "install", "--agent", "claude", "--path", str(repo)])
    assert held.exit_code == 5 and "-mine\n+v1\n" in held.stdout
    assert "rerun with --yes" in held.stderr
    done = runner.invoke(
        app, ["skills", "install", "--agent", "claude", "--path", str(repo), "--yes"]
    )
    assert done.exit_code == 0 and done.stdout == f"claude alpha: updated → {folder}\n{note}\n"


@pytest.mark.skipif(UV is None, reason="uv is not installed")
def test_the_wheel_carries_skills_and_roles(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    build = [str(UV), "build", "--wheel", "--quiet", "-o", str(tmp_path)]
    subprocess.run(build, cwd=root, check=True)
    (wheel,) = tmp_path.glob("*.whl")
    names = set(zipfile.ZipFile(wheel).namelist())
    assert {"kengash_ai/skills/README.md", "kengash_ai/roles/plan/SKILL.md"} <= names


PROBE = """\
skill: probe
turns: ["/probe"]
expect: {journal: [plan.created]}
"""
PLAN_NEW = "kengash plan new --mode direct --title Probe <<'EOF'\nAdd add(a, b).\nEOF"


def test_cli_eval_prints_one_line_per_run(
    tmp_path: Path, fake_clis: FakeClis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HARNESS_HOME", raising=False)
    (tmp_path / "evals" / "probe").mkdir(parents=True)
    (tmp_path / "evals" / "probe" / "one.yaml").write_text(PROBE, encoding="utf-8")
    reply = json.dumps({"session_id": "s-1", "result": "ok", "is_error": False})
    fake_clis.queue("claude", stdout=reply, shell=PLAN_NEW)
    fake_clis.queue("claude", stdout=reply)  # the second run does no work: it fails
    args = ["skills", "eval", "probe", "--agent", "claude", "--dir", str(tmp_path / "evals")]
    passed = runner.invoke(app, [*args, "--keep", str(tmp_path / "keep")])
    assert (passed.exit_code, passed.stdout.splitlines()[0]) == (0, "probe/one claude: pass")
    failed = runner.invoke(app, args)
    assert failed.exit_code == 1
    assert failed.stdout.splitlines()[0] == "probe/one claude: fail: journal has no plan.created"


def test_cli_eval_needs_the_named_agent(tmp_path: Path, fake_clis: FakeClis) -> None:
    (tmp_path / "evals" / "probe").mkdir(parents=True)
    (tmp_path / "evals" / "probe" / "one.yaml").write_text(PROBE, encoding="utf-8")
    fake_clis.hide("agy")
    result = runner.invoke(
        app, ["skills", "eval", "probe", "--agent", "agy", "--dir", str(tmp_path / "evals")]
    )
    assert result.exit_code == 4 and "antigravity not installed" in result.stderr


def test_cli_install_names_the_agy_fallback(
    tmp_path: Path, store_paths: StorePaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source" / "alpha"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("---\nname: alpha\ndescription: Use when.\n---\nv1\n")
    monkeypatch.setattr(skills, "packaged", lambda: tmp_path / "source")
    monkeypatch.setattr(skills, "_run", lambda argv: 1)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    result = runner.invoke(app, ["skills", "install", "--agent", "agy", "--path", str(repo)])
    folder = repo / ".agents" / "skills" / "kengash-alpha"
    note = "agy plugin install failed; copies instead"
    assert result.stdout == f"antigravity alpha: installed → {folder} ({note})\n"


def test_cli_show_renders_for_the_named_agent() -> None:
    shown = runner.invoke(app, ["skills", "show", "ticket", "--agent", "codex"])
    assert shown.exit_code == 0 and "`$kengash-loop`" in shown.stdout
    missing = runner.invoke(app, ["skills", "show", "nope"])
    assert missing.exit_code == 1 and missing.stderr.startswith("unknown skill: nope; known:")
