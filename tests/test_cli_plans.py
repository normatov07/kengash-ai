import json
from pathlib import Path

from typer.testing import CliRunner

from super_harness.cli import app

runner = CliRunner()
NEW = ["plan", "new", "--title", "Rotatable keys", "--mode"]


def test_plan_lifecycle(inside_registered_repo: Path) -> None:
    created = runner.invoke(app, [*NEW, "grill"], input="Rotate keys.\n")
    plan_id = created.stdout.split()[1]
    assert created.stdout == f"plan {plan_id} grilling\n"
    saved = runner.invoke(
        app, ["plan", "save", plan_id], input="## Goal\nShip it.\n## Scope\nKeys.\n"
    )
    assert saved.stdout == f"plan {plan_id} draft, 2 sections\n"
    shown = runner.invoke(app, ["plan", "show", plan_id]).stdout
    assert "\n## Prompt\nRotate keys.\n\n## Goal\nShip it.\n" in shown
    unreviewed = runner.invoke(app, ["plan", "approve", plan_id])
    assert unreviewed.exit_code == 5
    assert unreviewed.stderr.endswith("approve it with --skip-review\n")
    approved = runner.invoke(app, ["plan", "approve", plan_id, "--skip-review", "--by", "claude"])
    assert approved.stdout == f"plan {plan_id} approved\n"


def test_plan_json_and_reject(inside_registered_repo: Path) -> None:
    plan_id = runner.invoke(app, [*NEW, "direct"], input="Rotate keys.\n").stdout.split()[1]
    shown = json.loads(runner.invoke(app, ["plan", "show", plan_id, "--json"]).stdout)
    assert (shown["project"], shown["meta"]["status"], shown["sections"]["Prompt"]) == (
        "payments-api",
        "draft",
        "Rotate keys.",
    )
    rejected = runner.invoke(app, ["plan", "reject", plan_id, "--why", "too broad", "--json"])
    assert json.loads(rejected.stdout)["status"] == "rejected"


def test_plan_errors_exit_1(inside_registered_repo: Path) -> None:
    unknown = runner.invoke(app, ["plan", "save", "deadbeef"], input="## Goal\nx\n")
    assert (unknown.exit_code, unknown.stderr) == (1, "unknown plan: deadbeef\n")
    empty = runner.invoke(app, [*NEW, "direct"], input="")
    assert (empty.exit_code, empty.stderr) == (1, "the prompt is empty\n")
