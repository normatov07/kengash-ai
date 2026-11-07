"""Viewer tabs opened when a worker or a loop starts (SP13 spec §3.1, §3.2)."""

import os
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import pytest
from conftest import Engine, write_settings

from kengash_ai import journal
from kengash_ai.model import (
    Doc,
    Event,
    SessionRef,
    SlotEntry,
    SlotTable,
    Ticket,
    UserError,
    WorkerRecord,
)
from kengash_ai.ops import conductors, controls, loops, viewers, watch
from kengash_ai.ops.conductors import Conductor, process_name
from kengash_ai.store import StorePaths, documents, runtime

Make = Callable[..., Doc[Ticket]]


@pytest.fixture
def opened(
    store_paths: StorePaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[[], list[str]]:
    """Tabs open through a template that writes each title and command to a file."""
    monkeypatch.delenv("KENGASH_WATCH", raising=False)
    for name in ("TERM_PROGRAM", "TMUX", "DISPLAY", "WAYLAND_DISPLAY"):
        monkeypatch.delenv(name, raising=False)  # only the template can open a tab
    record = tmp_path / "tabs.txt"
    write_settings(store_paths, f'watch.terminal: "echo {{title}}: {{command}} >> {record}"\n')
    monkeypatch.setattr(controls, "spawn_worker", lambda *args: os.getpid())
    monkeypatch.setattr(watch, "cli_name", lambda: "kengash")
    return lambda: record.read_text(encoding="utf-8").splitlines() if record.exists() else []


def test_run_opens_one_tab_per_ticket(
    registered_repo: Path,
    store_paths: StorePaths,
    make_ticket: Make,
    opened: Callable[[], list[str]],
) -> None:
    documents.save_ticket(store_paths.project("payments-api"), make_ticket())
    (started,) = controls.run_tickets(["7b55e0c1"], by="claude").started
    assert opened() == ["kg 7b55e0c1: kengash logs 7b55e0c1 --watch"]
    assert started.watch == "custom tab kg 7b55e0c1"
    assert watch.open_ticket(store_paths, "payments-api", "7b55e0c1") == "custom tab kg 7b55e0c1"
    assert len(opened()) == 1  # the tab is still opening: its key is claimed


def test_a_live_viewer_keeps_its_tab(
    registered_repo: Path, store_paths: StorePaths, opened: Callable[[], list[str]]
) -> None:
    viewers.register(store_paths, "ticket-7b55e0c1")
    assert watch.open_ticket(store_paths, "payments-api", "7b55e0c1") == "custom tab kg 7b55e0c1"
    assert opened() == []


def test_tabs_off_or_watch_off_print_the_command(
    registered_repo: Path,
    store_paths: StorePaths,
    opened: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_settings(store_paths, "watch.tabs: off\n", slugs=("payments-api",))
    assert watch.open_ticket(store_paths, "payments-api", "7b55e0c1") == (
        "kengash logs 7b55e0c1 --watch"
    )
    monkeypatch.setenv("KENGASH_WATCH", "off")
    assert watch.open_dashboard(store_paths, None) == "kengash watch"
    assert opened() == []


def test_no_terminal_prints_the_command(
    registered_repo: Path, store_paths: StorePaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("KENGASH_WATCH", raising=False)
    monkeypatch.setattr(watch, "cli_name", lambda: "kengash")
    for name in ("TERM_PROGRAM", "TMUX", "DISPLAY", "WAYLAND_DISPLAY"):
        monkeypatch.delenv(name, raising=False)
    assert watch.open_ticket(store_paths, "payments-api", "7b55e0c1") == (
        "kengash logs 7b55e0c1 --watch"
    )


def test_a_new_loop_opens_one_dashboard(
    registered_repo: Path,
    store_paths: StorePaths,
    opened: Callable[[], list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    me = Conductor(os.getpid(), "claude", process_name(os.getpid()) or "", True)
    monkeypatch.setattr(conductors, "conductor", lambda: me)
    first = loops.claim("payments-api")
    assert first.watch == "custom tab kg watch payments-api"
    loops.claim("payments-api")  # the same conductor again: no new lease, no new tab
    assert opened() == ["kg watch payments-api: kengash watch -p payments-api"]


def test_attach_opens_the_workers_session_in_a_tab(
    engine: Engine, opened: Callable[[], list[str]]
) -> None:
    doc = engine.ticket()
    doc.meta.sessions["planner"] = SessionRef(provider="claude", model="opus", id="s-1")
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    assert watch.attach_tab("7b55e0c1", role=None, project=None) == "custom tab kg 7b55e0c1 planner"
    (line,) = opened()
    assert line.startswith("kg 7b55e0c1 planner: sh -c ") and "claude --resume s-1" in line


def test_attach_is_refused_while_a_worker_runs(engine: Engine) -> None:
    doc = engine.ticket()
    doc.meta.sessions["planner"] = SessionRef(provider="claude", model="opus", id="s-1")
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    worker = WorkerRecord(id="7b55e0c1", project=engine.slug, pid=os.getpid())
    runtime.save_worker(engine.paths, worker)
    with pytest.raises(UserError, match="a worker is running 7b55e0c1; attach once it stops"):
        watch.attach_tab("7b55e0c1", role=None, project=None)


def _gate(engine: Engine, ticket_id: str, status: str, reason: str) -> None:
    doc = make_ticket_doc(engine, ticket_id)
    doc.meta.status, doc.meta.step = status, "implement"
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    kind = "ticket." + status.split("/", 1)[1]
    data = {"type": kind, "project": engine.slug, "ticket": ticket_id, "reason": reason}
    journal.append(engine.paths, Event.model_validate(data))


def make_ticket_doc(engine: Engine, ticket_id: str) -> Doc[Ticket]:
    doc = engine.ticket()
    doc.meta.id, doc.meta.uuid = ticket_id, uuid4()
    doc.meta.title = f"Ticket {ticket_id}"
    return doc


def test_the_board_shows_workers_slots_tokens_gates_and_the_feed(busy_ticket: Engine) -> None:
    engine = busy_ticket
    end = {"type": "step.end", "project": engine.slug, "ticket": engine.ticket_id}
    tokens = {"in": 400_000, "out": 40_000}
    journal.append(
        engine.paths,
        Event.model_validate(
            {**end, "step": "plan", "verdict": "pass", "provider": "antigravity", "tokens": tokens}
        ),
    )
    held = SlotEntry(
        provider="antigravity",
        project=engine.slug,
        ticket=engine.ticket_id,
        step="implement",
        pid=os.getpid(),
    )
    runtime.save_slots(engine.paths, SlotTable(held=[held]))
    doc = engine.ticket()
    doc.meta.tokens = 498_000
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    _gate(engine, "0b1c2d3e", "in_process/needs_approval", "token cap: 1,010,000 of 1,000,000 used")
    _gate(engine, "1c2d3e4f", "in_process/awaiting_merge", "every step passed")
    board = watch.board(engine.paths, [engine.slug])
    assert board.loops == []
    assert board.slots["antigravity"] == (1, 2) and board.slots["claude"] == (0, 3)
    assert board.total == (1, 8) and board.tokens_today == {"antigravity": 440_000}
    (worker,) = board.workers
    assert (worker.id, worker.tokens, worker.tokens_max) == (engine.ticket_id, 498_000, 1_000_000)
    assert [(g.id, g.status, g.action) for g in board.gates] == [
        ("0b1c2d3e", "needs_approval", "kengash approve 0b1c2d3e"),
        ("1c2d3e4f", "awaiting_merge", "kengash merge 1c2d3e4f"),
    ]
    assert board.gates[0].reason.startswith("token cap: 1,010,000")
    texts = [item.text for _, item in board.feed]
    assert "reply: Rebrand core package and UI to Chess Samurai" in texts
    assert texts[-1] == "plan pass · 440k tokens"  # newest last
    assert all(ticket == engine.ticket_id for ticket, _ in board.feed)
    lines = watch.lines(board)
    assert lines[0] == "loops: no loop running"
    assert lines[1].startswith("slots: antigravity 1/2 · claude 0/3 · codex 0/3 · total 1/8")
    assert any(
        line.startswith(f"  {engine.ticket_id} payments-api implement→antigravity/flash")
        and "498k/1000k tokens" in line
        for line in lines
    )
    gate = "  0b1c2d3e needs_approval: token cap: 1,010,000 of 1,000,000 used"
    assert f"{gate} → kengash approve 0b1c2d3e" in lines


def test_an_empty_board(engine: Engine) -> None:
    doc = engine.ticket()
    doc.meta.status = "in_queue/ready"
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    lines = watch.lines(watch.board(engine.paths, [engine.slug]))
    assert lines[0] == "loops: no loop running" and "running: nothing" in lines


def test_a_long_gate_reason_is_cut(engine: Engine) -> None:
    _gate(engine, "0b1c2d3e", "in_process/failed", "crash: " + "x" * 2000)
    (gate,) = watch.board(engine.paths, [engine.slug]).gates
    assert len(gate.reason) == watch.REASON_MAX and gate.reason.endswith("…")
