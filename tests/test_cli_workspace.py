import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import COMPACTED, FakeClis, write_settings
from typer.testing import CliRunner

from super_harness.cli import app
from super_harness.model import Doc, Ticket
from super_harness.store import StorePaths, documents

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


def test_context_lists_open_gates(
    store_paths: StorePaths, inside_repo: Path, make_ticket: Callable[..., Doc[Ticket]]
) -> None:
    documents.save_ticket(
        store_paths.project("payments-api"), make_ticket(status="in_process/needs_approval")
    )
    text = runner.invoke(app, ["context"]).stdout
    assert "\n\n# PROCESS.md (payments-api)\n# PROCESS.md\n## Process notes\n\n" in text
    assert text.endswith("# Open gates\n- 7b55e0c1 needs_approval: Rotate keys\n")


def test_every_command_speaks_json(store_paths: StorePaths, inside_repo: Path) -> None:
    def call(*args: str) -> Any:
        return json.loads(runner.invoke(app, [*args, "--json"]).stdout)

    assert call("settings", "get", "merge.mode") == "ask"
    assert call("settings", "show")["loop_max"]["critical"] == 6
    assert call("settings", "check") == {"problems": []}
    assert call("memory", "add", "prefers runbooks", "--why", "said so") == {
        "compacting": False,
        "file": "MEMORY.md",
        "line": "- prefers runbooks",
        "lines": 13,
        "cap": 200,
        "added": True,
        "over_cap": False,
    }
    assert call("memory", "show") == {
        "file": "MEMORY.md",
        "text": (store_paths.memory / "MEMORY.md").read_text(encoding="utf-8"),
    }
    assert call("context") == {
        "memory": (store_paths.memory / "MEMORY.md").read_text(encoding="utf-8"),
        "project": "payments-api",
        "process": ["# PROCESS.md", "## Process notes"],
        "gates": [],
    }


def test_memory_compact_prints_the_line_counts_or_exits_1(
    inside_repo: Path, long_memory: Path, fake_clis: FakeClis
) -> None:
    long = long_memory.read_text(encoding="utf-8")
    fake_clis.queue("claude", stdout=fake_clis.claude_output({"text": COMPACTED}))
    done = runner.invoke(app, ["memory", "compact", "--timeout", "60"])
    assert (done.exit_code, done.stdout) == (0, "MEMORY.md 19 → 16 lines\n")
    long_memory.write_text(long, encoding="utf-8")
    fake_clis.queue("claude", stdout=fake_clis.claude_output({"text": "# MEMORY.md\n"}))
    kept = runner.invoke(app, ["memory", "compact", "--timeout", "60"])
    assert kept.exit_code == 1
    assert kept.stderr.startswith("MEMORY.md kept (19 lines): the result drops")


def test_memory_add_over_the_cap_compacts_in_the_background(
    inside_repo: Path, store_paths: StorePaths, fake_clis: FakeClis
) -> None:
    write_settings(store_paths, "memory.compact_at_lines: 12\n", slugs=(None,))
    short = (
        "# MEMORY.md\n\n## Working style\n\n- prefers runbooks\n\n"
        "## Goals\n\n## Preferences\n\n## Turned down\n"
    )
    fake_clis.queue("claude", stdout=fake_clis.claude_output({"text": short}))
    added = runner.invoke(app, ["memory", "add", "prefers runbooks", "--why", "said so"])
    assert added.stdout == (
        "MEMORY.md +1 line (13/12)\n"
        "MEMORY.md is over its 12-line cap; compacting it in the background\n"
    )
    path = store_paths.memory / "MEMORY.md"
    deadline = time.monotonic() + 20
    while path.read_text(encoding="utf-8") != short:
        assert time.monotonic() < deadline, "the background compaction never landed"
        time.sleep(0.1)
