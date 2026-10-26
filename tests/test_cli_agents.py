"""`harness agent new` and `harness agent remove` (SP6 spec decision 6)."""

import json
from pathlib import Path

from typer.testing import CliRunner

from super_harness.cli import app

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
