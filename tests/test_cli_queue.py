import json
from collections.abc import Callable
from pathlib import Path

from typer.testing import CliRunner

from kengash_ai.cli import app
from kengash_ai.model import Doc, Ticket
from kengash_ai.store import StorePaths, documents

runner = CliRunner()
Make = Callable[..., Doc[Ticket]]


def test_next_lists_runnable_tickets(
    inside_registered_repo: Path, store_paths: StorePaths, make_ticket: Make
) -> None:
    project = store_paths.project("payments-api")
    documents.save_ticket(project, make_ticket(touches=["services/webhooks"]))
    documents.save_ticket(project, make_ticket("a91b3d07", touches=["services/webhooks/keys"]))
    result = runner.invoke(app, ["next"])
    assert result.exit_code == 0
    assert result.stdout == "7b55e0c1 payments-api critical plan→claude Rotate keys\n"
    data = json.loads(runner.invoke(app, ["next", "--json"]).stdout)
    assert data["held_back"] == {"a91b3d07": "touches overlap 7b55e0c1"}


def test_next_says_why_nothing_can_run(
    inside_registered_repo: Path, store_paths: StorePaths, make_ticket: Make
) -> None:
    assert runner.invoke(app, ["next"]).stdout == "nothing runnable: the queue is empty\n"
    project = store_paths.project("payments-api")
    gate = make_ticket(status="in_process/needs_approval", step="implement")
    documents.save_ticket(project, gate)
    blocked = make_ticket("a91b3d07", status="in_queue/blocked", depends_on=["7b55e0c1"])
    documents.save_ticket(project, blocked)
    documents.save_ticket(project, make_ticket("3c9d0e11"))
    result = runner.invoke(app, ["next"])
    assert result.stdout == "nothing runnable: 1 held back, 1 blocked, 1 at gates\n"


def test_next_prints_at_most_five_lines(
    inside_registered_repo: Path, store_paths: StorePaths, make_ticket: Make
) -> None:
    project = store_paths.project("payments-api")
    for path in (store_paths.defaults / "SETTINGS.md", project.settings):
        roomy = path.read_text(encoding="utf-8").replace("claude: 3", "claude: 8")
        path.write_text(roomy, encoding="utf-8")
    for number in range(7):
        documents.save_ticket(project, make_ticket(f"aaaaaaa{number}", touches=[f"d{number}"]))
    lines = runner.invoke(app, ["next"]).stdout.splitlines()
    assert len(lines) == 5
    assert lines[-1] == "+3 more; run: kengash next --json"
