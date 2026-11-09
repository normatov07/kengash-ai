"""Detached workers: real processes running a ticket's steps with the fake CLIs."""

import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import Engine, FakeClis

from kengash_ai.model import PlanMode, PlanStatus, WorkerRecord
from kengash_ai.ops import controls, harvest, lifecycle, plans, records, tickets
from kengash_ai.store import StorePaths, documents, runtime


def wait_until(check: Callable[[], bool], within: float = 20.0) -> None:
    deadline = time.monotonic() + within
    while not check():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.1)


def test_a_detached_worker_runs_its_steps(engine: Engine, fake_clis: FakeClis) -> None:
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    pid = controls.spawn_worker(engine.paths, engine.slug, "7b55e0c1", 1)
    runtime.save_worker(engine.paths, WorkerRecord(id="7b55e0c1", project=engine.slug, pid=pid))
    wait_until(lambda: engine.ticket().meta.status == "in_process/paused")
    wait_until(lambda: runtime.load_worker(engine.paths, "7b55e0c1") is None)
    assert engine.ticket().meta.step == "implement"


def test_stop_ends_the_worker_and_its_cli(engine: Engine, fake_clis: FakeClis) -> None:
    fake_clis.queue("claude", fixture="claude/work_resume.json", sleep=60)
    pid = controls.spawn_worker(engine.paths, engine.slug, "7b55e0c1", None)
    runtime.save_worker(engine.paths, WorkerRecord(id="7b55e0c1", project=engine.slug, pid=pid))
    wait_until(lambda: len(fake_clis.calls("claude")) == 1)
    started = time.monotonic()
    assert controls.stop_ticket("7b55e0c1", project=None, by="user") == "in_process/failed"
    assert time.monotonic() - started < 12
    assert engine.ticket().meta.status == "in_process/failed"
    assert runtime.load_slots(engine.paths).held == []
    assert (
        subprocess.run(["pgrep", "-f", "fake_cli.py claude"], capture_output=True).returncode == 1
    )


@pytest.mark.parametrize(
    ("target", "status"), [("in_queue", "in_queue/ready"), ("done", "done/closed")]
)
def test_moving_a_running_ticket_out_of_process_stops_its_worker(
    engine: Engine, fake_clis: FakeClis, target: str, status: str
) -> None:
    fake_clis.queue("claude", fixture="claude/work_resume.json", sleep=60)
    pid = controls.spawn_worker(engine.paths, engine.slug, "7b55e0c1", None)
    runtime.save_worker(engine.paths, WorkerRecord(id="7b55e0c1", project=engine.slug, pid=pid))
    wait_until(lambda: len(fake_clis.calls("claude")) == 1)
    started = time.monotonic()
    moved = tickets.move_ticket("7b55e0c1", target, "send it back", project=None, by="user")
    assert time.monotonic() - started < 12
    assert (moved.after, moved.stopped) == (status, True)
    assert not lifecycle.pid_alive(pid)
    assert runtime.load_worker(engine.paths, "7b55e0c1") is None
    assert runtime.load_slots(engine.paths).held == []
    assert (
        subprocess.run(["pgrep", "-f", "fake_cli.py claude"], capture_output=True).returncode == 1
    )
    assert engine.ticket().meta.status == status


def test_the_worker_runs_a_plan_review(
    registered_repo: Path, store_paths: StorePaths, fake_clis: FakeClis
) -> None:
    made = plans.new_plan(
        "Rotate keys.",
        title="Rotatable keys",
        mode=PlanMode.direct,
        project=None,
        cwd=registered_repo,
        by="user",
    )
    plans.save_plan(
        made.id, "## Goal\nKeys rotate.\n## Lasting decisions\nnone\n", project=None, by="user"
    )
    _, path = records.locate_plan(store_paths, made.id, None)
    doc = records.load_plan(path)
    doc.meta.status, doc.meta.review.reviewer = PlanStatus.in_review, "claude"
    documents.save_plan(store_paths.project("payments-api"), doc)
    review = {"verdict": "pass", "summary": "Fine.", "findings": []}
    fake_clis.queue("claude", stdout=fake_clis.claude_output(review))
    worker = [sys.executable, "-m", "kengash_ai.worker", "plan-review", made.id]
    done = subprocess.run([*worker, "--project", "payments-api"], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout == f"{made.id}: round 1 pass\n"
    assert records.load_plan(path).meta.review.round == 1


def test_the_worker_drains_the_harvest_spool(
    registered_repo: Path, store_paths: StorePaths, fake_clis: FakeClis
) -> None:
    said = "the capture animations matter most in this game"
    assert harvest.submit(store_paths, "chat abc", "payments-api", said)
    fact = {
        "kind": "decision",
        "fact": "Capture animations come first",
        "why": "they matter most",
        "rejected": "",
        "quote": "capture animations matter most",
        "replaces": 0,
    }
    fake_clis.queue("claude", stdout=fake_clis.claude_output({"facts": [fact]}))
    worker = [sys.executable, "-m", "kengash_ai.worker", "harvest"]
    done = subprocess.run(worker, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout == "harvest: 1 lines from 1 texts\n"
    text = (store_paths.memory / "DECISIONS.md").read_text(encoding="utf-8")
    assert "[payments-api] (user) Capture animations come first." in text
    assert runtime.harvest_entries(store_paths) == []
