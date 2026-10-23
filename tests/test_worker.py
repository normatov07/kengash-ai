"""Detached workers: real processes running a ticket's steps with the fake CLIs."""

import subprocess
import time
from collections.abc import Callable

from conftest import Engine, FakeClis

from super_harness.model import WorkerRecord
from super_harness.ops import controls
from super_harness.store import runtime


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
