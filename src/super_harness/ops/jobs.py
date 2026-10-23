"""Detached job workers: start them, track their records, wait for their end
(SP3 spec decision 33).

A job journals one terminal event: its result (`plan.reviewed`, `memory.compacted`) or
`worker.exited` with `ok: false`. Callers wait for it from a journal cursor taken before
the job starts.
"""

import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from typing import Any

from super_harness import journal
from super_harness.model import Event, JournalCursor, SlotEntry, WorkerRecord, utc_now
from super_harness.ops import lifecycle, slots
from super_harness.store import runtime
from super_harness.store.paths import StorePaths

COMPACT = "compact"  # the compaction job's worker id; plan reviews use the plan id
SLOT_POLL_S = 5
sleep = time.sleep


def spawn(paths: StorePaths, args: Sequence[str], log_name: str) -> int:
    """Start `python -m super_harness.worker <args>` detached, logging to
    runtime/logs/<log_name>.log."""
    paths.logs.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, "-m", "super_harness.worker", *args]
    with (paths.logs / f"{log_name}.log").open("ab") as log:
        process = subprocess.Popen(
            argv,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=dict(os.environ),
        )
    return process.pid


def start(paths: StorePaths, job: str, job_id: str, project: str, args: Sequence[str]) -> int:
    """Spawn the job's worker and save its record."""
    pid = spawn(paths, args, job_id)
    record = WorkerRecord.model_validate({"id": job_id, "project": project, "pid": pid, "job": job})
    runtime.save_worker(paths, record)
    return pid


def alive(paths: StorePaths, job_id: str) -> WorkerRecord | None:
    """The job's record while its process lives and its heartbeat is fresh."""
    record = runtime.load_worker(paths, job_id)
    if record is None or not lifecycle.pid_alive(record.pid):
        return None
    if (utc_now() - record.heartbeat).total_seconds() >= lifecycle.DEAD_AFTER_S:
        return None
    return record


def heartbeat(job_id: str) -> None:
    """Refresh the job's heartbeat (the worker's beat thread calls this)."""
    runtime.beat(StorePaths.default(), job_id)


def forget(job_id: str) -> None:
    """Drop the worker record when it is this process's, so a newer worker's survives."""
    paths = StorePaths.default()
    record = runtime.load_worker(paths, job_id)
    if record is not None and record.pid == os.getpid():
        runtime.drop_worker(paths, job_id)


def exited(job: str, job_id: str, project: str | None, reason: str) -> Event:
    """The `worker.exited` event of a job that ended without its result."""
    data: dict[str, Any] = {
        "type": "worker.exited",
        "project": project or None,
        "job": job,
        "id": job_id,
        "ok": False,
        "reason": reason,
    }
    if job == "plan-review":
        data["plan"] = job_id
    return Event.model_validate(data)


def await_event(
    paths: StorePaths,
    cursor: JournalCursor,
    match: Callable[[Event], bool],
    job: str,
    job_id: str,
    *,
    timeout: float,
    poll_s: float = 0.5,
) -> Event | None:
    """The first event after `cursor` that `match`es; a synthetic `worker.exited` once the
    job's worker is gone without one; None at the timeout."""
    deadline = time.monotonic() + timeout
    while True:
        events, cursor = journal.read_after(paths, cursor)
        found = next((event for event in events if match(event)), None)
        if found is not None:
            return found
        if alive(paths, job_id) is None:
            events, cursor = journal.read_after(paths, cursor)  # it may have just written it
            found = next((event for event in events if match(event)), None)
            reason = f"worker died; log: {paths.logs / f'{job_id}.log'}"
            return found or exited(job, job_id, None, reason)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        sleep(min(poll_s, remaining))


def take_slot(paths: StorePaths, entry: SlotEntry) -> None:
    """Hold a slot for `entry.ticket`, heartbeating while it waits in line."""
    while not slots.acquire(paths, entry):
        runtime.beat(paths, entry.ticket)
        sleep(SLOT_POLL_S)


def died(paths: StorePaths, record: WorkerRecord) -> None:
    """Clean up after a job whose worker died: free its slot and journal its end."""
    slots.release(paths, record.id)
    journal.append(paths, exited(record.job, record.id, record.project, "worker died"))
