"""wait, the dead-worker check and conductor pings (SP3 spec decisions 9 and 24)."""

import json
import os
from datetime import timedelta
from pathlib import Path

import pytest
from conftest import Engine, Events

from super_harness.model import TicketState, WorkerRecord, utc_now
from super_harness.ops import lifecycle, steps, waiting
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
