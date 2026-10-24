"""Controls: run claims tickets; approve, park, stop, pause, resume (SP3 spec decision 8)."""

import os
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import Engine, Events, FakeClis

from super_harness.model import (
    Doc,
    NeedsSetup,
    Ticket,
    TicketState,
    UserError,
    WorkerRecord,
)
from super_harness.ops import controls
from super_harness.ops.controls import Paused, Resumed, Started
from super_harness.store import StorePaths, documents, runtime

Make = Callable[..., Doc[Ticket]]


@pytest.fixture
def spawned(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int | None]]:
    calls: list[tuple[str, int | None]] = []

    def spawn(paths: StorePaths, slug: str, ticket_id: str, steps: int | None) -> int:
        calls.append((ticket_id, steps))
        return os.getpid()  # a live pid, as a real worker's would be

    monkeypatch.setattr(controls, "spawn_worker", spawn)
    return calls


def test_run_claims_a_ready_ticket(
    registered_repo: Path,
    store_paths: StorePaths,
    make_ticket: Make,
    spawned: list[tuple[str, int | None]],
    journal_events: Events,
) -> None:
    project = store_paths.project("payments-api")
    documents.save_ticket(project, make_ticket(importance="simple", workflow="simple", loop_max=3))
    result = controls.run_tickets(["7b55e0c1"], steps=2, by="claude")
    assert result.started == [
        Started("7b55e0c1", "payments-api", "plan", "claude")
    ] and spawned == [("7b55e0c1", 2)]
    path = documents.find_ticket(project, "7b55e0c1")
    assert path is not None
    doc = documents.load_ticket(path)
    assert (doc.meta.status, doc.meta.step, doc.meta.branch) == (
        "in_process/under_planning",
        "plan",
        "hrn/7b55e0c1",
    )
    assert store_paths.worktree("payments-api", "7b55e0c1").is_dir()
    worker = runtime.load_worker(store_paths, "7b55e0c1")
    assert worker is not None and worker.pid == os.getpid()
    assert [e.ticket for e in runtime.load_slots(store_paths).waiting] == ["7b55e0c1"]
    assert journal_events()[-1]["type"] == "ticket.claimed"


def test_run_skips_with_reasons(
    registered_repo: Path,
    store_paths: StorePaths,
    make_ticket: Make,
    spawned: list[tuple[str, int | None]],
) -> None:
    project = store_paths.project("payments-api")
    documents.save_ticket(project, make_ticket(importance="simple", workflow="simple", loop_max=3))
    documents.save_ticket(
        project, make_ticket("a91b3d07", importance="simple", workflow="simple", loop_max=3)
    )
    documents.save_ticket(project, make_ticket("3c9d0e11", status="in_queue/parked"))
    result = controls.run_tickets(["7b55e0c1", "a91b3d07", "3c9d0e11"], by="claude")
    assert [s.id for s in result.started] == ["7b55e0c1"]
    assert result.skipped == {
        "a91b3d07": "touches overlap 7b55e0c1",
        "3c9d0e11": "status in_queue/parked",
    }
    again = controls.run_tickets(["7b55e0c1"], by="claude")
    assert again.skipped == {"7b55e0c1": "already running"} and len(spawned) == 1


def test_run_needs_a_usable_provider_and_no_sandbox(
    registered_repo: Path,
    store_paths: StorePaths,
    make_ticket: Make,
    fake_clis: FakeClis,
    monkeypatch: pytest.MonkeyPatch,
    spawned: list[tuple[str, int | None]],
) -> None:
    documents.save_ticket(
        store_paths.project("payments-api"),
        make_ticket(importance="simple", workflow="simple", loop_max=3),
    )
    fake_clis.sign_out("claude")
    with pytest.raises(NeedsSetup, match="planner cannot run: claude signed out"):
        controls.run_tickets(["7b55e0c1"], by="claude")
    monkeypatch.setenv("CODEX_SANDBOX_NETWORK_DISABLED", "1")
    with pytest.raises(NeedsSetup, match="network-less codex sandbox"):
        controls.run_tickets(["7b55e0c1"], by="codex")


def test_approve_grants_loops_and_restarts(
    engine: Engine, spawned: list[tuple[str, int | None]]
) -> None:
    doc = engine.ticket()
    doc.meta.status, doc.meta.step, doc.meta.loop = "in_process/needs_approval", "implement", 3
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    runtime.save_ticket_state(engine.paths, "7b55e0c1", TicketState(approval="loop_cap"))
    approved = controls.approve_ticket("7b55e0c1", loops=2, tokens=None, project=None, by="user")
    assert approved.status == "in_process/under_implementation" and spawned == [("7b55e0c1", None)]
    assert (engine.ticket().meta.loop, engine.ticket().meta.loop_max) == (4, 5)
    with pytest.raises(UserError, match="7b55e0c1 is not waiting for approval"):
        controls.approve_ticket("7b55e0c1", loops=None, tokens=None, project=None, by="user")


def test_park_defers_while_a_worker_runs(engine: Engine) -> None:
    runtime.save_worker(
        engine.paths, WorkerRecord(id="7b55e0c1", project=engine.slug, pid=os.getpid())
    )
    assert controls.park_ticket("7b55e0c1", "later", project=None, by="user").deferred
    assert runtime.park_requested(engine.paths, "7b55e0c1")
    runtime.drop_worker(engine.paths, "7b55e0c1")
    assert not controls.park_ticket("7b55e0c1", "later", project=None, by="user").deferred
    assert engine.ticket().meta.status == "in_queue/parked"


def test_pause_and_resume(engine: Engine, spawned: list[tuple[str, int | None]]) -> None:
    assert controls.pause("payments-api", by="user") == Paused("payments-api", 0)
    doc = engine.ticket()
    doc.meta.status = "in_process/paused"
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    assert controls.resume("payments-api", by="user") == Resumed(["7b55e0c1"])
    assert not runtime.pause_state(engine.paths).covers("payments-api")


def test_resuming_a_stalled_ticket_clears_its_plan_rounds(
    registered_repo: Path,
    store_paths: StorePaths,
    make_ticket: Make,
    spawned: list[tuple[str, int | None]],
) -> None:
    project = store_paths.project("payments-api")
    stalled = make_ticket(
        importance="standard",
        workflow="standard",
        status="in_process/stalled",
        step="review_plan",
    )
    documents.save_ticket(project, stalled)
    streaks = {"review_plan": {"a1b2c3d4e5f6": 2}}
    runtime.save_ticket_state(store_paths, "7b55e0c1", TicketState(plan_rounds=2, streaks=streaks))
    assert controls.run_tickets(["7b55e0c1"], steps=None, by="user").started
    state = runtime.load_ticket_state(store_paths, "7b55e0c1")
    assert (state.plan_rounds, state.streaks) == (0, {})
