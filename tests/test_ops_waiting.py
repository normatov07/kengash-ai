"""wait, the dead-worker check and conductor pings (SP3 spec decisions 9 and 24)."""

import json
import os
from datetime import timedelta
from pathlib import Path

import pytest
from conftest import Engine, Events

from super_harness import journal
from super_harness.model import (
    Event,
    PlanMode,
    PlanStatus,
    SlotEntry,
    SlotTable,
    TicketState,
    WorkerRecord,
    utc_now,
)
from super_harness.ops import lifecycle, plans, records, steps, waiting
from super_harness.store import StorePaths, documents, runtime


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
    monkeypatch.setenv("HARNESS_AGENT", "codex")
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
