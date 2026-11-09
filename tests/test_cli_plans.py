import json
from pathlib import Path

from conftest import FakeClis
from typer.testing import CliRunner, Result

from kengash_ai.cli import app
from kengash_ai.store import StorePaths

runner = CliRunner()
NEW = ["plan", "new", "--title", "Rotatable keys", "--mode"]


def test_plan_lifecycle(inside_registered_repo: Path) -> None:
    created = runner.invoke(app, [*NEW, "grill"], input="Rotate keys.\n")
    plan_id = created.stdout.split()[1]
    assert created.stdout == f"plan {plan_id} grilling\n"
    saved = runner.invoke(
        app,
        ["plan", "save", plan_id],
        input="## Goal\nShip it.\n## Lasting decisions\nnone\n## Scope\nKeys.\n",
    )
    assert saved.stdout == f"plan {plan_id} draft, 3 sections\n"
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


FINDINGS = [
    {"severity": "high", "file": "Design", "line": 0, "issue": "no expiry", "fix": "add one"},
    {"severity": "low", "file": "README.md", "line": 2, "issue": "typo", "fix": "fix it"},
]
FAIL = {"verdict": "fail", "summary": "Gaps.", "findings": FINDINGS}
REVIEW = ["plan", "review", "--by", "codex", "--timeout", "60"]


def reviewable() -> str:
    plan_id = runner.invoke(app, [*NEW, "direct"], input="Rotate keys.\n").stdout.split()[1]
    runner.invoke(
        app,
        ["plan", "save", plan_id],
        input="## Goal\nShip it.\n## Lasting decisions\nnone\n## Scope\nKeys.\n",
    )
    return plan_id


def review(plan_id: str, *extra: str) -> Result:
    return runner.invoke(app, [*REVIEW[:2], plan_id, *REVIEW[2:], *extra])


def test_plan_review_runs_a_round_and_prints_its_findings(
    inside_registered_repo: Path, fake_clis: FakeClis
) -> None:
    plan_id = reviewable()
    fake_clis.queue("claude", stdout=fake_clis.claude_output(FAIL))
    result = review(plan_id)
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == [
        f"plan {plan_id} round 1: fail, 2 findings",
        "- round 1 · high · Design:0 · no expiry · add one",
        "- round 1 · low · README.md:2 · typo · fix it",
    ]
    again = review(plan_id)
    assert again.stdout == result.stdout and len(fake_clis.calls("claude")) == 1


def test_a_failing_last_round_and_a_review_after_it_exit_5(
    inside_registered_repo: Path, store_paths: StorePaths, fake_clis: FakeClis
) -> None:
    store_paths.project("payments-api").settings.write_text(
        "plan.review_max: 1\n", encoding="utf-8"
    )
    plan_id = reviewable()
    fake_clis.queue("claude", stdout=fake_clis.claude_output(FAIL))
    last = review(plan_id)
    assert last.exit_code == 5 and last.stdout.startswith(f"plan {plan_id} round 1: fail")
    assert last.stderr == (
        "review rounds used up (1/1): the user approves the plan as it is or rejects it\n"
    )
    runner.invoke(app, ["plan", "save", plan_id], input="## Risks\nNone.\n")
    after = review(plan_id)
    assert after.exit_code == 5 and "used up" in after.stderr
    assert len(fake_clis.calls("claude")) == 1


def test_a_timed_out_review_keeps_running_and_a_second_call_waits_for_it(
    inside_registered_repo: Path, fake_clis: FakeClis
) -> None:
    plan_id = reviewable()
    fake_clis.queue("claude", stdout=fake_clis.claude_output(FAIL), sleep=2)
    first = runner.invoke(app, ["plan", "review", plan_id, "--by", "codex", "--timeout", "0.3"])
    assert first.exit_code == 3 and "still running" in first.stderr
    second = review(plan_id)
    assert second.exit_code == 0 and second.stdout.startswith(f"plan {plan_id} round 1: fail")
    assert len(fake_clis.calls("claude")) == 1


def test_plan_review_needs_review_on_and_sections_to_review(
    inside_registered_repo: Path, store_paths: StorePaths
) -> None:
    bare = runner.invoke(app, [*NEW, "direct"], input="Rotate keys.\n").stdout.split()[1]
    empty = review(bare)
    assert empty.exit_code == 1 and "nothing to review" in empty.stderr
    store_paths.project("payments-api").settings.write_text(
        "plan.review_max: 0\n", encoding="utf-8"
    )
    off = review(reviewable())
    assert off.exit_code == 1 and "plan review is off" in off.stderr


def test_cli_approve_prints_decisions_count(inside_registered_repo: Path) -> None:
    plan_id = runner.invoke(app, [*NEW, "quick"], input="Rotate keys.\n").stdout.split()[1]
    body = "## Goal\nShip it.\n## Lasting decisions\n- keyring over env var. why: rotation.\n"
    runner.invoke(app, ["plan", "save", plan_id], input=body)
    approved = runner.invoke(app, ["plan", "approve", plan_id])
    assert approved.stdout == f"plan {plan_id} approved\nDECISIONS.md +1 line\n"
