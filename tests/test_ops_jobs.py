"""Job workers: start, track, wait for their end (SP3 spec decision 33)."""

import os
import time
from datetime import timedelta

from conftest import Events

from kengash_ai import journal
from kengash_ai.model import Event, WorkerRecord, utc_now
from kengash_ai.ops import jobs, lifecycle
from kengash_ai.store import StorePaths, runtime


def test_spawn_starts_a_detached_worker_that_logs(store_paths: StorePaths) -> None:
    pid = jobs.spawn(store_paths, ["--help"], "probe")
    deadline = time.monotonic() + 20
    while lifecycle.pid_alive(pid):
        assert time.monotonic() < deadline
        time.sleep(0.05)
    assert "usage:" in (store_paths.logs / "probe.log").read_text(encoding="utf-8")


def test_start_saves_the_worker_record(store_paths: StorePaths) -> None:
    pid = jobs.start(store_paths, "compact", jobs.COMPACT, "", ["--help"])
    record = runtime.load_worker(store_paths, jobs.COMPACT)
    assert record is not None and (record.job, record.pid, record.project) == ("compact", pid, "")


def test_alive_needs_a_live_pid_and_a_fresh_heartbeat(store_paths: StorePaths) -> None:
    own = WorkerRecord(id="a1b2c3d4", project="payments-api", pid=os.getpid(), job="plan-review")
    runtime.save_worker(store_paths, own)
    assert jobs.alive(store_paths, "a1b2c3d4") == runtime.load_worker(store_paths, "a1b2c3d4")
    runtime.save_worker(store_paths, own.model_copy(update={"pid": 2**22 + 7}))
    assert jobs.alive(store_paths, "a1b2c3d4") is None
    old = utc_now() - timedelta(seconds=lifecycle.DEAD_AFTER_S + 5)
    runtime.save_worker(store_paths, own.model_copy(update={"heartbeat": old}))
    assert jobs.alive(store_paths, "a1b2c3d4") is None
    assert jobs.alive(store_paths, "ffffffff") is None


def test_await_event_returns_the_first_match_after_the_cursor(store_paths: StorePaths) -> None:
    journal.append(store_paths, Event(type="plan.reviewed", plan="a1b2c3d4", round=1))
    cursor = journal.end(store_paths)
    journal.append(store_paths, Event(type="plan.saved", plan="a1b2c3d4"))
    journal.append(store_paths, Event(type="plan.reviewed", plan="a1b2c3d4", round=2))
    runtime.save_worker(
        store_paths,
        WorkerRecord(id="a1b2c3d4", project="p", pid=os.getpid(), job="plan-review"),
    )
    found = jobs.await_event(
        store_paths,
        cursor,
        lambda e: e.type == "plan.reviewed",
        "plan-review",
        "a1b2c3d4",
        timeout=1,
    )
    assert found is not None and (found.model_extra or {})["round"] == 2


def test_await_event_reports_a_dead_worker(store_paths: StorePaths) -> None:
    found = jobs.await_event(
        store_paths, journal.end(store_paths), lambda e: False, "compact", "compact", timeout=1
    )
    assert found is not None and found.type == "worker.exited"
    assert (found.model_extra or {})["job"] == "compact"
    assert (found.model_extra or {})["reason"].startswith("worker died; log: ")


def test_await_event_times_out(store_paths: StorePaths) -> None:
    runtime.save_worker(
        store_paths,
        WorkerRecord(id="a1b2c3d4", project="p", pid=os.getpid(), job="plan-review"),
    )
    started = time.monotonic()
    found = jobs.await_event(
        store_paths,
        journal.end(store_paths),
        lambda e: False,
        "plan-review",
        "a1b2c3d4",
        timeout=0.2,
        poll_s=0.05,
    )
    assert found is None and time.monotonic() - started < 2


def test_exited_names_the_job_and_its_plan(journal_events: Events) -> None:
    event = jobs.exited("plan-review", "a1b2c3d4", "payments-api", "boom")
    data = event.model_dump(exclude_none=True)
    assert data | {"ts": None} == {
        "ts": None,
        "type": "worker.exited",
        "project": "payments-api",
        "plan": "a1b2c3d4",
        "job": "plan-review",
        "id": "a1b2c3d4",
        "ok": False,
        "reason": "boom",
    }


def test_old_logs_are_pruned_and_new_ones_kept(store_paths: StorePaths) -> None:
    store_paths.logs.mkdir(parents=True)
    now = time.time()
    ages = {"old-1.out": 31, "fresh-1.out": 29, "ui.log": 0}
    for name, days in ages.items():
        path = store_paths.logs / name
        path.write_text("x")
        os.utime(path, (now - days * 86400, now - days * 86400))
    assert jobs.prune_logs(store_paths, keep_days=0) == 0  # 0 keeps everything
    assert jobs.prune_logs(store_paths, keep_days=30) == 1
    assert sorted(p.name for p in store_paths.logs.iterdir()) == ["fresh-1.out", "ui.log"]
    assert jobs.prune_logs(store_paths, keep_days=30) == 0
