"""Independent tickets run side by side with real detached workers and the fake CLIs, and
a ticket whose paths overlap a running one waits (SP13 spec §3.9)."""

from collections.abc import Callable

from conftest import Engine, Events, FakeClis
from test_lifecycle import REVIEW_PASS, wait_until
from typer.testing import CliRunner

from kengash_ai.cli import app
from kengash_ai.model import Doc, Ticket
from kengash_ai.ops import records
from kengash_ai.store import documents, runtime

runner = CliRunner()
WRITE = 'echo done > "$(basename "$PWD").txt"'  # a file of its own per worktree


def test_two_independent_tickets_run_at_once_and_both_merge(
    engine: Engine,
    make_ticket: Callable[..., Doc[Ticket]],
    fake_clis: FakeClis,
    run_git: Callable[..., str],
    journal_events: Events,
) -> None:
    project = engine.paths.project(engine.slug)
    documents.save_ticket(project, _ready(make_ticket, "7b55e0c1", "retry/"))  # engine's own
    documents.save_ticket(project, _ready(make_ticket, "0b1c2d3e", "billing/"))
    documents.save_ticket(project, _ready(make_ticket, "1c2d3e4f", "retry/backoff.py"))
    # both plans first: the two workers take replies in step order, not ticket order
    for _ in range(2):
        fake_clis.queue("claude", fixture="claude/work_resume.json", sleep=1.5)  # plan
    for _ in range(2):
        fake_clis.queue("codex", fixture="codex/work_resume.jsonl", shell=WRITE)  # implement
    for _ in range(2):
        fake_clis.queue("claude", stdout=fake_clis.claude_output(REVIEW_PASS))  # review_code
    started = runner.invoke(app, ["run", "7b55e0c1", "0b1c2d3e", "1c2d3e4f"]).stdout
    assert "started 7b55e0c1 plan→claude" in started and "started 0b1c2d3e plan→claude" in started
    assert "skipped 1c2d3e4f: touches overlap" in started
    statuses = ("in_process/awaiting_merge",)
    wait_until(lambda: _statuses(engine, ["7b55e0c1", "0b1c2d3e"]) == set(statuses), 60)
    events = journal_events()
    starts = [e["ticket"] for e in events if e["type"] == "step.start" and e["step"] == "plan"]
    first_end = next(i for i, e in enumerate(events) if e["type"] == "step.end")
    before = {e["ticket"] for e in events[:first_end] if e["type"] == "step.start"}
    assert sorted(starts) == ["0b1c2d3e", "7b55e0c1"] and before == {"0b1c2d3e", "7b55e0c1"}
    for ticket_id in ("7b55e0c1", "0b1c2d3e"):
        merged = runner.invoke(app, ["merge", ticket_id])
        assert merged.exit_code == 0, merged.stdout + merged.stderr
    files = run_git(engine.repo, "ls-tree", "--name-only", "main").split()
    assert {"kg-7b55e0c1.txt", "kg-0b1c2d3e.txt"} <= set(files)
    wait_until(lambda: runtime.load_workers(engine.paths) == [])


def _ready(make: Callable[..., Doc[Ticket]], ticket_id: str, touches: str) -> Doc[Ticket]:
    doc = make(
        ticket_id,
        importance="simple",
        workflow="simple",
        loop_max=3,
        touches=[touches],
        status="in_queue/ready",
    )
    doc.sections["Acceptance"] = "- [ ] it works"
    return doc


def _statuses(engine: Engine, ids: list[str]) -> set[str]:
    tickets = records.project_tickets(engine.paths, engine.slug)
    return {tickets[i].meta.status for i in ids}
