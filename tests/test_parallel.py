"""Independent tickets run side by side with real detached workers and the fake CLIs, and
a ticket whose paths overlap an editing one plans at once, then waits to edit (SP13 spec §3.9;
SP16 spec §3.7, §3.8)."""

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
AWAITING = "in_process/awaiting_merge"


def test_tickets_plan_at_once_and_an_overlapping_one_waits_to_edit(
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
    # each reply names its ticket's worktree, so no worker takes another ticket's reply,
    # whatever order they run in
    for ticket_id in ("7b55e0c1", "0b1c2d3e", "1c2d3e4f"):
        mine = f"kg-{ticket_id}"
        fake_clis.queue("claude", fixture="claude/work_resume.json", sleep=4, match=mine)
        fake_clis.queue("codex", fixture="codex/work_resume.jsonl", shell=WRITE, match=mine)
        fake_clis.queue("claude", stdout=fake_clis.claude_output(REVIEW_PASS), match=mine)
    started = runner.invoke(app, ["run", "7b55e0c1", "0b1c2d3e", "1c2d3e4f"]).stdout
    for ticket_id in ("7b55e0c1", "0b1c2d3e", "1c2d3e4f"):  # planning edits nothing (SP16)
        assert f"started {ticket_id} plan→claude" in started
    # 7b55e0c1 and 1c2d3e4f overlap: whichever plans first edits first; the other waits
    pair = ("7b55e0c1", "1c2d3e4f")
    wait_until(lambda: _settled(engine, pair), 60)
    tickets = records.project_tickets(engine.paths, engine.slug)
    first = next(i for i in pair if tickets[i].meta.status == AWAITING)
    waiter = next(i for i in pair if i != first)
    events = journal_events()
    first_end = next(i for i, e in enumerate(events) if e["type"] == "step.end")
    before = {e["ticket"] for e in events[:first_end] if e["type"] == "step.start"}
    assert before == {"0b1c2d3e", "1c2d3e4f", "7b55e0c1"}
    waited = [e for e in events if e["type"] == "ticket.waiting"]
    assert {(e["ticket"], e["holder"]) for e in waited} == {(waiter, first)}
    for ticket_id in (first, "0b1c2d3e"):
        merged = runner.invoke(app, ["merge", ticket_id])
        assert merged.exit_code == 0, merged.stdout + merged.stderr
    wait_until(lambda: _statuses(engine, [waiter]) == {AWAITING}, 60)
    files = run_git(engine.repo, "ls-tree", "--name-only", "main").split()
    assert {f"kg-{first}.txt", "kg-0b1c2d3e.txt"} <= set(files)
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


def _settled(engine: Engine, pair: tuple[str, str]) -> bool:
    """0b1c2d3e and one of the overlapping pair wait to merge; the other waits to edit."""
    tickets = records.project_tickets(engine.paths, engine.slug)
    statuses = sorted(tickets[i].meta.status for i in pair)
    alone = tickets["0b1c2d3e"].meta.status == AWAITING
    return alone and statuses == [AWAITING, "in_process/waiting_paths"]


def _statuses(engine: Engine, ids: list[str]) -> set[str]:
    tickets = records.project_tickets(engine.paths, engine.slug)
    return {tickets[i].meta.status for i in ids}
