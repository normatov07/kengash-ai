"""Detached job workers: start them, track their records, wait for their end
(SP3 spec decision 33).

A job journals one terminal event: its result (`plan.reviewed`, `memory.compacted`) or
`worker.exited` with `ok: false`. Callers wait for it from a journal cursor taken before
the job starts.
"""

import contextlib
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from typing import Any

from kengash_ai import journal, settings
from kengash_ai.model import (
    Event,
    JournalCursor,
    KengashError,
    Logs,
    SlotEntry,
    WorkerRecord,
    utc_now,
)
from kengash_ai.ops import lifecycle, slots
from kengash_ai.store import runtime
from kengash_ai.store.paths import StorePaths

COMPACT = "compact"  # the compaction job's worker id; plan reviews use the plan id
SLOT_POLL_S = 5
STOP_GRACE_S = 10
sleep = time.sleep


def spawn(paths: StorePaths, args: Sequence[str], log_name: str) -> int:
    """Start `python -m kengash_ai.worker <args>` detached, logging to
    runtime/logs/<log_name>.log; logs older than `logs.keep_days` go first."""
    paths.logs.mkdir(parents=True, exist_ok=True)
    prune_logs(paths, keep_days(paths))
    argv = [sys.executable, "-m", "kengash_ai.worker", *args]
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


def end(paths: StorePaths, job_id: str) -> bool:
    """Kill the job's worker while its process runs (SIGTERM to its process group, SIGKILL
    after STOP_GRACE_S), then drop its record; False when no worker runs."""
    record = runtime.load_worker(paths, job_id)
    if record is None or not lifecycle.pid_alive(record.pid):
        return False
    _end_group(record.pid)
    runtime.drop_worker(paths, job_id)
    return True


def keep_days(paths: StorePaths) -> int:
    """`logs.keep_days` of the user's defaults; the package default when they are broken."""
    try:
        return settings.load(paths).logs.keep_days
    except KengashError:
        return Logs().keep_days


def prune_logs(paths: StorePaths, keep_days: int, *, now: float | None = None) -> int:
    """Remove files in runtime/logs untouched for more than `keep_days` days (SP7 spec
    decision 7); 0 keeps everything. Returns how many were removed."""
    if keep_days <= 0 or not paths.logs.is_dir():
        return 0
    cutoff = (time.time() if now is None else now) - keep_days * 86400
    removed = 0
    for path in paths.logs.iterdir():
        with contextlib.suppress(OSError):  # gone already, or written to right now
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
    return removed


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


def _end_group(pid: int) -> None:
    """SIGTERM the worker's process group, then SIGKILL it after STOP_GRACE_S."""
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    deadline = time.monotonic() + STOP_GRACE_S
    while lifecycle.pid_alive(pid):
        if time.monotonic() >= deadline:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(pid, signal.SIGKILL)
            break
        time.sleep(0.1)
