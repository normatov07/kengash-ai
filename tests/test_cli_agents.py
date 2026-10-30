"""`kengash agent new` and `kengash agent remove` (SP6 spec decision 6)."""

import json
from pathlib import Path

from typer.testing import CliRunner

from kengash_ai.cli import app

runner = CliRunner()
NEW = [
    "agent",
    "new",
    "perf-reviewer",
    "--kind",
    "review",
    "--does",
    "Flag N+1 queries.",
    "--cli",
    "claude/sonnet",
    "--workflow",
    "critical",
    "--after",
    "review_code",
    "--step",
    "perf_review",
    "--project",
    "payments-api",
]


def test_cli_agent_new_and_remove(registered_repo: Path) -> None:
    added = runner.invoke(app, NEW)
    assert added.exit_code == 0, added.output
    assert added.output == (
        "added perf-reviewer: step perf_review in critical; skill roles/perf-reviewer/SKILL.md\n"
    )
    removed = runner.invoke(app, ["agent", "remove", "perf-reviewer", "-p", "payments-api"])
    assert (removed.exit_code, removed.output) == (0, "removed perf-reviewer\n")
    again = runner.invoke(app, [*NEW, "--json"])
    assert json.loads(again.output)["keys"] == [
        "agents.perf-reviewer",
        "steps.perf_review",
        "workflows.critical",
    ]


def test_cli_agent_new_names_the_problem(registered_repo: Path) -> None:
    refused = runner.invoke(
        app, ["agent", "new", "code-reviewer", "--kind", "review", "--does", "x"]
    )
    assert refused.exit_code == 1 and "exists" in refused.output


def invoke(*args: str, stdin: str | None = None) -> tuple[int, str]:
    result = runner.invoke(app, list(args), input=stdin)
    return result.exit_code, result.output


def test_cli_agent_new_takes_fallbacks_and_instructions(registered_repo: Path) -> None:
    code, _ = invoke(
        *NEW,
        "--fallback",
        "claude/haiku,antigravity",
        "--instructions-file",
        "-",
        stdin="Speed only.\n",
    )
    assert code == 0
    code, out = invoke("agent", "show", "perf-reviewer", "-p", "payments-api", "--json")
    shown = json.loads(out)
    assert (shown["fallback"], shown["instructions"], shown["instructions_own"]) == (
        ["claude/haiku", "antigravity"],
        "Speed only.\n",
        True,
    )
    assert shown["used_in"] == [{"workflow": "critical", "position": 5}]


def test_cli_agent_edit(registered_repo: Path, tmp_path: Path) -> None:
    assert invoke(*NEW)[0] == 0
    text = tmp_path / "perf.md"
    text.write_text("Measure first.\n")
    code, out = invoke(
        "agent",
        "edit",
        "perf-reviewer",
        "--cli",
        "codex",
        "--off",
        "--instructions-file",
        str(text),
        "-p",
        "payments-api",
    )
    assert (code, out) == (
        0,
        "edited perf-reviewer: agents.perf-reviewer.cli, agents.perf-reviewer.on; "
        "instructions roles/perf-reviewer/SKILL.md\n",
    )
    shown = json.loads(invoke("agent", "show", "perf-reviewer", "-p", "payments-api", "--json")[1])
    assert (shown["cli"], shown["on"], shown["instructions"]) == (
        "codex",
        False,
        "Measure first.\n",
    )
    code, out = invoke("agent", "edit", "planner", "--kind", "read")
    assert code == 1 and "planner is a built-in agent; its kind is fixed" in out


def test_cli_agent_copy_and_show(registered_repo: Path) -> None:
    code, out = invoke("agent", "copy", "code-reviewer", "strict-reviewer")
    assert (code, out) == (0, "copied code-reviewer to strict-reviewer: step strict_reviewer\n")
    code, out = invoke("agent", "show", "strict-reviewer")
    lines = out.splitlines()
    assert code == 0 and lines[0] == "strict-reviewer · yours · review · step strict_reviewer · on"
    assert "used in: no workflow" in lines


def test_cli_workflow_commands(registered_repo: Path) -> None:
    assert invoke("workflow", "new", "hotfix", "--from", "simple") == (0, "added workflow hotfix\n")
    assert invoke("workflow", "route", "critical", "hotfix") == (0, "critical tickets run hotfix\n")
    assert invoke("workflow", "rename", "hotfix", "quickfix") == (
        0,
        "renamed workflow hotfix to quickfix\n",
    )
    code, out = invoke(
        "workflow",
        "set",
        "quickfix",
        "--steps",
        "plan,implement,review_code",
        "--on-fail",
        "review_code=implement",
    )
    assert (code, out) == (0, "set workflow quickfix: plan → implement → review_code\n")
    code, out = invoke("workflow", "remove", "quickfix")
    assert code == 1 and "workflow quickfix is routed from critical" in out
    code, out = invoke("workflow", "set", "quickfix", "--steps", "plan", "--on-fail", "review_code")
    assert code == 1 and "--on-fail takes STEP=TARGET" in out
    shown = json.loads(invoke("workflow", "route", "critical", "critical", "--json")[1])
    assert shown["keys"] == ["routing.critical"]


def test_cli_names_an_instructions_file_it_cannot_read(
    registered_repo: Path, tmp_path: Path
) -> None:
    assert invoke(*NEW)[0] == 0
    missing = tmp_path / "nope.md"
    code, out = invoke(
        "agent", "edit", "perf-reviewer", "--instructions-file", str(missing), "-p", "payments-api"
    )
    assert code == 1 and f"cannot read {missing}" in out and "Traceback" not in out
