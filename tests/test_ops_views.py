"""Read models for the UI screens (SP5 spec §3)."""

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from super_harness import journal
from super_harness.model import ConductorPing, Doc, Event, SlotEntry, SlotTable, Ticket, utc_now
from super_harness.ops import views
from super_harness.store import StorePaths, documents, runtime

Make = Callable[..., Doc[Ticket]]


def step_end(ticket: str, provider: str, tokens: int, *, added: int = 0, ago: int = 0) -> Event:
    return Event.model_validate(
        {
            "ts": utc_now() - timedelta(days=ago),
            "type": "step.end",
            "project": "payments-api",
            "ticket": ticket,
            "step": "implement",
            "provider": provider,
            "tokens": {"in": tokens, "out": 0},
            "added": added,
            "removed": 1,
        }
    )


@pytest.fixture
def seeded(registered_repo: Path, store_paths: StorePaths, make_ticket: Make) -> StorePaths:
    project = store_paths.project("payments-api")
    for doc in (
        make_ticket("aaaaaaa1", status="in_queue/ready", touches=["a"], title="<script>x</script>"),
        make_ticket("aaaaaaa2", status="in_queue/blocked", touches=[]),
        make_ticket("aaaaaaa3", status="in_process/under_implementation", step="implement"),
        make_ticket("aaaaaaa4", status="in_process/needs_approval", step="security", loop=6),
        make_ticket("aaaaaaa5", status="done/merged"),
    ):
        documents.save_ticket(project, doc)
    for event in (
        step_end("aaaaaaa3", "codex", 1000, added=128),
        step_end("aaaaaaa3", "claude", 500, added=2, ago=3),
        Event.model_validate(
            {
                "type": "ticket.needs_approval",
                "project": "payments-api",
                "ticket": "aaaaaaa4",
                "status": "in_process/needs_approval",
                "reason": "loop cap 6/6",
            }
        ),
        Event(type="ticket.merged", project="payments-api", ticket="aaaaaaa5"),
    ):
        journal.append(store_paths, event)
    held = SlotEntry(
        provider="codex", project="payments-api", ticket="aaaaaaa3", step="implement", pid=1
    )
    runtime.save_slots(store_paths, SlotTable(held=[held]))
    runtime.save_ping(store_paths, ConductorPing(pid=4242, agent="claude", project=None))
    return store_paths


def test_an_empty_store_has_an_empty_overview(store_paths: StorePaths) -> None:
    empty = views.overview(store_paths, window="today")
    assert (empty.projects, empty.sessions, empty.gates, empty.tail) == ([], [], [], [])
    assert all(not column.cards for column in views.board(store_paths, project=None).columns)


def test_the_overview_counts_sessions_queue_gates_and_spend(seeded: StorePaths) -> None:
    found = views.overview(seeded, window="today")
    assert found.projects == ["payments-api"]
    assert [(s.ticket, s.step) for s in found.sessions] == [("aaaaaaa3", "implement")]
    assert (found.queue.ready, found.queue.blocked, found.queue.parallel, found.queue.serial) == (
        1,
        1,
        1,
        1,
    )
    (gate,) = found.gates
    assert (gate.ticket, gate.reason, gate.loop) == ("aaaaaaa4", "loop cap 6/6", 6)
    assert found.done_today == 1
    assert found.spend == {"codex": 1000}
    assert views.overview(seeded, window="7d").spend == {"codex": 1000, "claude": 500}
    codex = next(slot for slot in found.slots if slot.provider == "codex")
    assert (codex.used, codex.total) == (1, 3)
    assert [c.agent for c in found.conductors] == ["claude"]
    assert found.tail[-1]["type"] == "ticket.merged"


def test_the_board_puts_cards_in_their_columns(seeded: StorePaths) -> None:
    columns = {c.key: c for c in views.board(seeded, project=None).columns}
    assert [card.id for card in columns["in_queue"].cards] == ["aaaaaaa1", "aaaaaaa2"]
    assert [card.id for card in columns["implement"].cards] == ["aaaaaaa3"]
    assert [card.id for card in columns["needs_you"].cards] == ["aaaaaaa4"]
    assert [card.id for card in columns["done"].cards] == ["aaaaaaa5"]
    card: Any = columns["implement"].cards[0]
    assert (card.added, card.removed, card.provider) == (130, 2, "codex")
    assert columns["in_queue"].cards[0].title == "<script>x</script>"  # escaped by the UI
