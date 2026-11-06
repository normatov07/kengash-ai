"""wait, the dead-worker check and conductor pings (SP3 spec decisions 9 and 24)."""

import json
import os
from datetime import timedelta
from pathlib import Path

import pytest
from conftest import Engine, Events

from kengash_ai import journal
from kengash_ai.model import (
    Event,
    JournalCursor,
    PlanMode,
    PlanStatus,
    SlotEntry,
    SlotTable,
    TicketState,
    WorkerRecord,
    utc_now,
)
from kengash_ai.ops import conductors, lifecycle, merging, plans, records, steps, tickets, waiting
from kengash_ai.ops.conductors import Conductor, process_name
from kengash_ai.store import StorePaths, documents, runtime


def test_a_dead_worker_fails_its_ticket(engine: Engine, journal_events: Events) -> None:
    runtime.save_worker(
        engine.paths, WorkerRecord(id="7b55e0c1", project=engine.slug, pid=2**22 + 7)
    )
    assert waiting.check_workers(engine.paths) == ["7b55e0c1"]
    doc = engine.ticket()
    assert doc.meta.status == "in_process/failed" and doc.meta.step == "plan"
    event = journal_events()[-1]
    assert (event["type"], event["reason"]) == ("ticket.failed", "worker died")
    assert runtime.load_worker(engine.paths, "7b55e0c1") is None


def test_dead_job_workers_are_dropped_and_free_their_slot(
    engine: Engine, journal_events: Events
) -> None:
    held = SlotEntry(
        provider="claude", project=engine.slug, ticket="a1b2c3d4", step="review_plan", pid=1
    )
    runtime.save_slots(engine.paths, SlotTable(held=[held]))
    runtime.save_worker(
        engine.paths,
        WorkerRecord(id="a1b2c3d4", project=engine.slug, pid=2**22 + 7, job="plan-review"),
    )
    assert waiting.check_workers(engine.paths) == ["a1b2c3d4"]
    assert runtime.load_worker(engine.paths, "a1b2c3d4") is None
    assert runtime.load_slots(engine.paths).held == []
    event = journal_events()[-1]
    assert (event["type"], event["job"], event["reason"]) == (
        "worker.exited",
        "plan-review",
        "worker died",
    )
    assert engine.ticket().meta.status == "in_process/under_planning"


def test_a_stale_heartbeat_counts_as_dead(engine: Engine) -> None:
    old = utc_now() - timedelta(seconds=lifecycle.DEAD_AFTER_S + 5)
    runtime.save_worker(
        engine.paths,
        WorkerRecord(id="7b55e0c1", project=engine.slug, pid=os.getpid(), heartbeat=old),
    )
    assert waiting.check_workers(engine.paths, fix=False) == ["7b55e0c1"]
    assert engine.ticket().meta.status == "in_process/under_planning"


def test_wait_reports_open_gates_first_then_new_events_once(engine: Engine) -> None:
    doc = engine.ticket()
    doc.meta.status = "in_process/needs_approval"
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    first = waiting.wait(None, timeout=1)
    assert [(e.id, e.status) for e in first.events] == [("7b55e0c1", "in_process/needs_approval")]
    assert waiting.wait(None, timeout=1).idle  # nothing running, nothing new
    steps.fail_ticket(engine.paths, engine.slug, "7b55e0c1", "boom")  # a gate already: no change
    doc = engine.ticket()
    doc.meta.status = "in_process/under_implementation"
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    steps.fail_ticket(engine.paths, engine.slug, "7b55e0c1", "boom")
    second = waiting.wait(None, timeout=1)
    assert [(e.status, e.detail) for e in second.events] == [("in_process/failed", "boom")]


def test_wait_times_out_while_work_runs(engine: Engine) -> None:
    runtime.save_ticket_state(engine.paths, "7b55e0c1", TicketState())
    runtime.save_worker(
        engine.paths, WorkerRecord(id="7b55e0c1", project=engine.slug, pid=os.getpid())
    )
    waiting.wait(None, timeout=0.1)  # sets the cursor
    result = waiting.wait(None, timeout=0.3, poll_s=0.1)
    assert result.timed_out and not result.events


def test_ping_records_the_conductor(
    store_paths: StorePaths, registered_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HARNESS_AGENT", "codex")  # the 0.1.0 name, still read
    waiting.ping(store_paths, "payments-api")
    [ping] = [json.loads(p.read_text()) for p in store_paths.conductors.glob("[0-9]*.json")]
    assert (ping["agent"], ping["project"]) == ("codex", "payments-api")


def test_wait_reports_plan_reviews_and_reviewed_plans_awaiting_approval(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    plan_id = plans.new_plan(
        "Rotate keys.",
        title="Keys",
        mode=PlanMode.direct,
        project=None,
        cwd=registered_repo,
        by="x",
    ).id
    assert waiting.wait(None, timeout=1).idle  # first call: no gates; sets the cursor
    _, path = records.locate_plan(store_paths, plan_id, None)
    doc = records.load_plan(path)
    doc.meta.status, doc.meta.review.round, doc.meta.review.verdict = (
        PlanStatus.in_review,
        1,
        "fail",
    )
    documents.save_plan(store_paths.project("payments-api"), doc)
    event = {"round": 1, "max": 2, "verdict": "fail", "summary": "Gaps."}
    journal.append(
        store_paths,
        Event.model_validate(
            {"type": "plan.reviewed", "project": "payments-api", "plan": plan_id, **event}
        ),
    )
    (found,) = waiting.wait(None, timeout=1).events
    assert (found.kind, found.id, found.status, found.loop, found.loop_max, found.detail) == (
        "plan",
        plan_id,
        "fail",
        1,
        2,
        "Gaps.",
    )
    (gate,) = waiting.wait("payments-api", timeout=1).events  # a new scope: open gates first
    assert (gate.kind, gate.id, gate.status, gate.loop) == ("plan", plan_id, "in_review", 1)


def test_a_running_plan_review_is_not_idle(registered_repo: Path, store_paths: StorePaths) -> None:
    runtime.save_worker(
        store_paths,
        WorkerRecord(id="a1b2c3d4", project="payments-api", pid=os.getpid(), job="plan-review"),
    )
    waiting.wait(None, timeout=0.1)  # sets the cursor
    assert waiting.wait(None, timeout=0.2, poll_s=0.05).timed_out


def test_kengash_agent_wins_over_the_old_name(
    store_paths: StorePaths, registered_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HARNESS_AGENT", "codex")
    monkeypatch.setenv("KENGASH_AGENT", "claude")
    waiting.ping(store_paths, "payments-api")
    [ping] = [json.loads(p.read_text()) for p in store_paths.conductors.glob("[0-9]*.json")]
    assert ping["agent"] == "claude"


def test_wait_is_never_idle_over_a_gate_its_worker_is_journaling(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worker saves its ticket at a gate, journals the gate, then exits; a `wait` that read
    the journal just before that event must report it, not `idle`."""
    runtime.save_worker(
        engine.paths, WorkerRecord(id="7b55e0c1", project=engine.slug, pid=os.getpid())
    )
    waiting.wait(None, timeout=0.1)  # sets the cursor
    real_read = journal.read_after
    finished: list[bool] = []

    def read_then_the_worker_finishes(
        paths: StorePaths, cursor: JournalCursor
    ) -> tuple[list[Event], JournalCursor]:
        found = real_read(paths, cursor)
        if not finished:
            finished.append(True)
            doc = engine.ticket()
            before, doc.meta.status = doc.meta.status, "in_process/awaiting_merge"
            documents.save_ticket(engine.paths.project(engine.slug), doc)
            event = lifecycle.status_event(engine.slug, doc.meta, before, "every step passed")
            journal.append(engine.paths, event)
            runtime.drop_worker(engine.paths, "7b55e0c1")
        return found

    monkeypatch.setattr(journal, "read_after", read_then_the_worker_finishes)
    result = waiting.wait(None, timeout=2, poll_s=0.05)
    assert [(e.id, e.status) for e in result.events] == [("7b55e0c1", "in_process/awaiting_merge")]


ME = Conductor(os.getpid(), "claude", process_name(os.getpid()) or "", True)
BATCH = """
- key: first
  title: Add keyring
  importance: simple
  touches: [keys]
  scope: The keyring.
  acceptance: [it loads]
- key: second
  title: Rotate keys
  importance: simple
  touches: [keys/rotate]
  depends_on: [first]
  scope: Rotation.
  acceptance: [it rotates]
"""


def test_wait_claims_for_a_detected_agent(
    registered_repo: Path, store_paths: StorePaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(conductors, "conductor", lambda: ME)
    assert waiting.wait("payments-api", timeout=0.1).idle
    lease = runtime.load_lease(store_paths, ME.pid)
    assert lease is not None and (lease.project, lease.agent) == ("payments-api", "claude")


def test_wait_from_an_undetected_caller_writes_no_lease(
    registered_repo: Path, store_paths: StorePaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    shell = Conductor(ME.pid, "unknown", ME.command, False)
    monkeypatch.setattr(conductors, "conductor", lambda: shell)
    assert waiting.wait(None, timeout=0.1).idle
    assert runtime.load_leases(store_paths) == []


def test_wait_reports_queued_for_ready_adds_and_unblocks_only(
    registered_repo: Path, store_paths: StorePaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(conductors, "conductor", lambda: ME)
    plan_id = plans.new_plan(
        "Keys.", title="Keys", mode=PlanMode.quick, project=None, cwd=registered_repo, by="x"
    ).id
    assert waiting.wait(None, timeout=0.1).idle  # sets the cursor
    first, second = tickets.add_tickets(plan_id, BATCH, project=None, by="x").tickets
    (queued,) = waiting.wait(None, timeout=0.1).events
    assert (queued.id, queued.status, queued.loop, queued.loop_max, queued.detail) == (
        first.id,
        "queued",
        1,
        3,
        "Add keyring",
    )
    journal.append(store_paths, merging._unblocked("payments-api", second.id, first.id))
    (unblocked,) = waiting.wait(None, timeout=0.1).events
    assert (unblocked.id, unblocked.status, unblocked.detail) == (
        second.id,
        "queued",
        "Rotate keys",
    )
