import json
from collections.abc import Callable
from pathlib import Path

from typer.testing import CliRunner

from super_harness.cli import app
from super_harness.model import Doc, Ticket
from super_harness.store import StorePaths, documents

runner = CliRunner()
BATCH = """\
- key: keyring
  title: Keyring with overlap window
  importance: critical
- key: rotate
  title: Rotation command
  importance: standard
  depends_on: [keyring]
"""


def approved_plan() -> str:
    new = ["plan", "new", "--title", "Keys", "--mode", "direct"]
    plan_id = runner.invoke(app, new, input="Rotate keys.\n").stdout.split()[1]
    runner.invoke(app, ["plan", "approve", plan_id, "--skip-review"])
    return plan_id


def test_ticket_flow(inside_registered_repo: Path) -> None:
    added = runner.invoke(app, ["ticket", "add", "--plan", approved_plan()], input=BATCH)
    keyring, rotate = added.stdout.split(": ", 1)[1].split(" (")[0].split(", ")
    assert added.stdout == f"2 tickets: {keyring}, {rotate} (1 ready, 1 blocked)\n"
    listed = runner.invoke(app, ["ticket", "list"]).stdout.splitlines()
    assert f"{keyring} in_queue/ready critical payments-api: Keyring with overlap window" in listed
    assert runner.invoke(app, ["ticket", "find", "ROTATION"]).stdout.startswith(f"{rotate} ")
    moved = runner.invoke(app, ["ticket", "move", keyring, "done", "--why", "shipped"])
    assert moved.stdout == f"ticket {keyring} → done/closed\nready: {rotate}\n"
    updated = runner.invoke(app, ["ticket", "set", rotate, "tags=[api]"])
    assert updated.stdout == f"ticket {rotate} updated\n"
    assert "\ntags: [api]\n" in runner.invoke(app, ["ticket", "show", rotate]).stdout
    board = runner.invoke(app, ["status"]).stdout
    assert board == "payments-api: 1 in_queue, 0 in_process, 1 done\n"


def test_ticket_add_reads_a_file_and_speaks_json(
    inside_registered_repo: Path, tmp_path: Path
) -> None:
    plan_id = approved_plan()
    batch = tmp_path / "tickets.json"
    batch.write_text(json.dumps([{"title": "Docs", "importance": "simple"}]), encoding="utf-8")
    added = runner.invoke(app, ["ticket", "add", "--plan", plan_id, "--file", str(batch), "--json"])
    data = json.loads(added.stdout)
    assert (data["plan"], data["tickets"][0]["status"]) == (plan_id, "in_queue/ready")
    listed = json.loads(runner.invoke(app, ["ticket", "list", "--json"]).stdout)
    assert [item["title"] for item in listed] == ["Docs"]


def test_a_bad_batch_exits_1_with_one_line(inside_registered_repo: Path) -> None:
    batch = "- {title: x, importance: simple, scop: y}\n"
    result = runner.invoke(app, ["ticket", "add", "--plan", approved_plan()], input=batch)
    assert (result.exit_code, result.stderr) == (
        1,
        "ticket 1: scop: unknown field; did you mean scope?\n",
    )


def test_status_prints_at_most_five_lines(
    store_paths: StorePaths,
    inside_registered_repo: Path,
    make_ticket: Callable[..., Doc[Ticket]],
) -> None:
    project = store_paths.project("payments-api")
    for n in range(6):
        documents.save_ticket(project, make_ticket(f"aaaaaaa{n}", status="in_process/stalled"))
    lines = runner.invoke(app, ["status"]).stdout.splitlines()
    assert lines[:2] == [
        "payments-api: 0 in_queue, 6 in_process, 0 done",
        "- aaaaaaa0 stalled: Rotate keys (payments-api)",
    ]
    assert (len(lines), lines[-1]) == (5, "+3 more; run: harness status --json")
