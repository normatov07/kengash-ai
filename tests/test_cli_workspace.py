from pathlib import Path

import pytest
from typer.testing import CliRunner

from super_harness.cli import app
from super_harness.store import StorePaths

runner = CliRunner()


@pytest.fixture
def inside_repo(store_paths: StorePaths, repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    runner.invoke(app, ["init", str(repo)])
    monkeypatch.chdir(repo)
    return repo


def test_settings_commands(store_paths: StorePaths, inside_repo: Path) -> None:
    assert runner.invoke(app, ["settings", "get", "loop_max.critical"]).stdout == "6\n"
    planner = runner.invoke(app, ["settings", "get", "agents.planner"]).stdout
    assert planner.startswith('{"on": true, "cli": "claude/opus"')
    assert (
        "loop_max: {simple: 3, standard: 4, critical: 6}\n"
        in runner.invoke(app, ["settings", "show"]).stdout
    )
    check = runner.invoke(app, ["settings", "check"])
    assert (check.exit_code, check.stdout) == (0, "")
    store_paths.project("payments-api").settings.write_text(
        "loop_max.critcal: 1\n", encoding="utf-8"
    )
    bad = runner.invoke(app, ["settings", "check"])
    assert (bad.exit_code, bad.stdout) == (
        1,
        "unknown key loop_max.critcal; did you mean loop_max.critical?\n",
    )


def test_memory_commands_and_context(inside_repo: Path) -> None:
    added = runner.invoke(app, ["memory", "add", "prefers runbooks", "--why", "said so"])
    assert added.stdout == "MEMORY.md +1 line (13/200)\n"
    again = runner.invoke(app, ["memory", "add", "prefers runbooks", "--why", "said so"])
    assert again.stdout == "MEMORY.md: already recorded\n"
    decided = runner.invoke(
        app, ["memory", "add", "keyring over secret", "--why", "rotation", "--decision"]
    )
    assert decided.stdout.startswith("DECISIONS.md +1 line")
    shown = runner.invoke(app, ["memory", "show", "--decisions"]).stdout
    assert "[payments-api] keyring over secret. why: rotation." in shown
    context = runner.invoke(app, ["context"]).stdout
    assert "- prefers runbooks" in context
    assert context.endswith("# Open gates\nnone\n")


def test_memory_errors_exit_1(inside_repo: Path) -> None:
    result = runner.invoke(app, ["memory", "add", "x", "--why", "y", "--section", "Hobbies"])
    assert result.exit_code == 1
    assert result.stderr.startswith("unknown section 'Hobbies'")


def test_context_without_a_store_exits_4(
    store_paths: StorePaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["context"])
    assert (result.exit_code, result.stderr) == (4, "no store yet; run: harness init\n")
