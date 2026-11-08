"""A ticket too large for one splits into parts (SP17 spec §3.6)."""

from collections.abc import Callable

import pytest
from conftest import Engine, Events, FakeClis

from kengash_ai.model import Doc, Part, Settings, Ticket
from kengash_ai.ops import records, steps, tickets
from kengash_ai.store import StorePaths, documents

SECTIONS = {"Scope": "All of it.", "Acceptance": "- [ ] one works\n- [ ] two works"}


def _files(prefix: str, count: int) -> list[str]:
    return [f"{prefix}{n}.py" for n in range(count)]


def _parts(**first: object) -> list[Part]:
    return [
        Part(title="First", scope="a", acceptance=["one works"], files=_files("a", 8), **first),
        Part(title="Second", scope="b", acceptance=["two works"], files=_files("b", 8), after=[0]),
    ]


def _ticket(make: Callable[..., Doc[Ticket]], **fields: object) -> Doc[Ticket]:
    doc = make("7b55e0c1", loop=1, **fields)
    doc.sections.update(SECTIONS)
    return doc


def test_a_good_split_has_no_problem(make_ticket: Callable[..., Doc[Ticket]]) -> None:
    doc = _ticket(make_ticket)
    assert tickets.split_problem(doc.meta, doc.sections, _parts(), Settings()) == ""


@pytest.mark.parametrize(
    ("change", "said"),
    [
        (lambda parts: parts[:1], "at least 2"),
        (lambda parts: [parts[0].model_copy(update={"acceptance": []}), parts[1]], "one works"),
        (lambda parts: [parts[0], parts[1].model_copy(update={"after": [1]})], "earlier"),
        (lambda parts: [parts[0], parts[1].model_copy(update={"files": []})], "no files"),
    ],
)
def test_a_bad_split_is_refused(
    make_ticket: Callable[..., Doc[Ticket]], change: Callable[..., list[Part]], said: str
) -> None:
    doc = _ticket(make_ticket)
    assert said in tickets.split_problem(doc.meta, doc.sections, change(_parts()), Settings())


def test_a_later_loop_is_refused(make_ticket: Callable[..., Doc[Ticket]]) -> None:
    doc = _ticket(make_ticket)
    doc.meta.loop = 2
    assert "first loop" in tickets.split_problem(doc.meta, doc.sections, _parts(), Settings())


def test_a_small_plan_is_not_split(make_ticket: Callable[..., Doc[Ticket]]) -> None:
    doc = _ticket(make_ticket)
    parts = [p.model_copy(update={"files": ["a.py"]}) for p in _parts()]
    assert "12" in tickets.split_problem(doc.meta, doc.sections, parts, Settings())


def test_splitting_off_refuses(make_ticket: Callable[..., Doc[Ticket]]) -> None:
    doc = _ticket(make_ticket)
    resolved = Settings(plan={"max_files": 0})
    assert "off" in tickets.split_problem(doc.meta, doc.sections, _parts(), resolved)


def test_split_narrows_the_ticket_and_queues_the_rest(
    store_paths: StorePaths,
    registered_repo: object,
    make_ticket: Callable[..., Doc[Ticket]],
) -> None:
    project = store_paths.project("payments-api")
    doc = _ticket(make_ticket, status="in_process/under_planning", step="plan")
    documents.save_ticket(project, doc)
    waiting = make_ticket("aaaa2222", depends_on=["7b55e0c1"], status="in_queue/blocked")
    documents.save_ticket(project, waiting)
    events = tickets.split(store_paths, "payments-api", doc, _parts(), by="planner")
    documents.save_ticket(project, doc)
    assert doc.meta.title == "First" and doc.meta.touches == _files("a", 8)
    assert doc.sections["Scope"] == "a"
    assert doc.sections["Acceptance"] == "- [ ] one works"
    [new] = [e.ticket for e in events]
    found = records.project_tickets(store_paths, "payments-api")
    part = found[str(new)].meta
    assert part.title == "Second" and part.depends_on == ["7b55e0c1"]
    assert part.status == "in_queue/blocked" and part.touches == _files("b", 8)
    assert found["aaaa2222"].meta.depends_on == ["7b55e0c1", new]
    assert found[str(new)].sections["Acceptance"] == "- [ ] two works"


def test_a_part_with_no_after_can_start_at_once(
    store_paths: StorePaths,
    registered_repo: object,
    make_ticket: Callable[..., Doc[Ticket]],
) -> None:
    project = store_paths.project("payments-api")
    doc = _ticket(make_ticket, status="in_process/under_planning", step="plan")
    documents.save_ticket(project, doc)
    parts = _parts()
    parts[1] = parts[1].model_copy(update={"after": []})
    [event] = tickets.split(store_paths, "payments-api", doc, parts, by="planner")
    assert records.project_tickets(store_paths, "payments-api")[str(event.ticket)].meta.status == (
        "in_queue/ready"
    )


def test_the_planner_splits_through_the_step_loop(
    engine: Engine, fake_clis: FakeClis, journal_events: Events
) -> None:
    doc = engine.ticket()
    doc.sections.update(SECTIONS)
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    output = {
        "summary": "split",
        "handoff": "Files: a0.py: start",
        "files": _files("a", 8) + _files("b", 8),
        "decisions": [],
        "parts": [p.model_dump() for p in _parts()],
    }
    fake_clis.queue("claude", stdout=fake_clis.claude_output(output))
    steps.run_job("7b55e0c1", steps=1)
    after = engine.ticket()
    assert after.meta.title == "First" and len(after.meta.touches) == 8
    assert [e for e in journal_events() if e["type"] == "ticket.created"][-1]["title"] == "Second"
    assert "split into 2 parts" in after.sections["Log"]


def test_a_refused_split_keeps_the_ticket_whole(engine: Engine, fake_clis: FakeClis) -> None:
    doc = engine.ticket()
    doc.sections.update(SECTIONS)
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    title = doc.meta.title
    parts = _parts()
    parts[1] = parts[1].model_copy(update={"acceptance": []})
    output = {
        "summary": "split",
        "handoff": "h",
        "files": _files("a", 16),
        "decisions": [],
        "parts": [p.model_dump() for p in parts],
    }
    fake_clis.queue("claude", stdout=fake_clis.claude_output(output))
    steps.run_job("7b55e0c1", steps=1)
    after = engine.ticket()
    assert after.meta.title == title and "split refused" in after.sections["Log"]
