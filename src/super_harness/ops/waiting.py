"""Wait for gates, find dead workers, record conductor pings (SP3 spec decisions 9, 24)."""

import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from super_harness import journal
from super_harness.model import ConductorPing, Event, Folder, Ticket, utc_now
from super_harness.ops import lifecycle, records, steps
from super_harness.ops.workspace import GATES
from super_harness.store import runtime
from super_harness.store.paths import StorePaths

WAIT_TYPES = (
    "ticket.needs_approval",
    "ticket.stalled",
    "ticket.failed",
    "ticket.awaiting_merge",
    "ticket.merged",
)
NOT_RUNNING = (*GATES, "paused")
AGENTS = ("claude", "codex", "agy")
ANCESTORS = 20


@dataclass
class WaitEvent:
    id: str
    project: str
    status: str
    loop: int
    loop_max: int
    detail: str


@dataclass
class WaitResult:
    events: list[WaitEvent] = field(default_factory=list)
    idle: bool = False
    timed_out: bool = False


def dead_workers(paths: StorePaths) -> list[tuple[str, str]]:
    """(project, ticket) of every worker record whose process is gone or whose heartbeat
    is older than DEAD_AFTER_S."""
    dead: list[tuple[str, str]] = []
    for record in runtime.load_workers(paths):
        age = (utc_now() - record.heartbeat).total_seconds()
        if age >= lifecycle.DEAD_AFTER_S or not lifecycle.pid_alive(record.pid):
            dead.append((record.project, record.id))
    return dead


def check_workers(paths: StorePaths, *, fix: bool = True) -> list[str]:
    """Tickets whose worker died; with `fix`, each running one fails "worker died"."""
    dead = dead_workers(paths)
    if fix:
        for slug, ticket_id in dead:
            steps.fail_ticket(paths, slug, ticket_id, "worker died")
            runtime.drop_worker(paths, ticket_id)
    return [ticket_id for _, ticket_id in dead]


def ping(paths: StorePaths, project: str | None) -> None:
    """Record the conductor: the nearest ancestor named claude, codex or agy, else the
    parent; its agent is $HARNESS_AGENT, else the detected name, else `unknown`."""
    pid, detected = _conductor()
    agent = os.environ.get("HARNESS_AGENT") or detected or "unknown"
    runtime.save_ping(paths, ConductorPing(pid=pid, agent=agent, project=project))


def wait(project: str | None, *, timeout: float, poll_s: float = 1.0) -> WaitResult:
    """Block until a ticket in scope needs the conductor; each event is reported once."""
    paths = StorePaths.default()
    slugs = records.scope(paths, project)
    scope = project or "all"
    check_workers(paths)
    ping(paths, project)
    cursor = runtime.load_cursor(paths, scope)
    if cursor is None:
        cursor = journal.end(paths)  # saved before the scan, so no gate slips between them
        runtime.save_cursor(paths, scope, cursor)
        gates = _open_gates(paths, slugs)
        if gates:
            return WaitResult(events=gates)
    deadline = time.monotonic() + timeout
    while True:
        events, cursor = journal.read_after(paths, cursor)
        runtime.save_cursor(paths, scope, cursor)
        found = [_wait_event(paths, event) for event in events if _wanted(event, slugs)]
        if found:
            return WaitResult(events=found)
        if not _running(paths, slugs):
            return WaitResult(idle=True)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return WaitResult(timed_out=True)
        time.sleep(min(poll_s, remaining))
        check_workers(paths)


def _wanted(event: Event, slugs: list[str]) -> bool:
    if event.project not in slugs:
        return False
    if event.type in WAIT_TYPES:
        return True
    return event.type == "ticket.moved" and str(_extra(event, "to")).startswith("done/")


def _wait_event(paths: StorePaths, event: Event) -> WaitEvent:
    status = _extra(event, "status") or _extra(event, "to")
    loop, loop_max = _extra(event, "loop"), _extra(event, "loop_max")
    if loop is None or loop_max is None:
        ticket = _ticket(paths, str(event.project), str(event.ticket))
        loop, loop_max = (ticket.loop, ticket.loop_max) if ticket else (0, 0)
    return WaitEvent(
        id=str(event.ticket),
        project=str(event.project),
        status=str(status),
        loop=int(loop),
        loop_max=int(loop_max),
        detail=str(_extra(event, "reason") or _extra(event, "why") or ""),
    )


def _open_gates(paths: StorePaths, slugs: list[str]) -> list[WaitEvent]:
    return [
        WaitEvent(
            doc.meta.id, slug, doc.meta.status, doc.meta.loop, doc.meta.loop_max, doc.meta.title
        )
        for slug in slugs
        for doc in records.project_tickets(paths, slug).values()
        if doc.meta.folder is Folder.in_process and doc.meta.sub_status in GATES
    ]


def _running(paths: StorePaths, slugs: list[str]) -> bool:
    return any(
        doc.meta.folder is Folder.in_process and doc.meta.sub_status not in NOT_RUNNING
        for slug in slugs
        for doc in records.project_tickets(paths, slug).values()
    )


def _ticket(paths: StorePaths, slug: str, ticket_id: str) -> Ticket | None:
    doc = records.project_tickets(paths, slug).get(ticket_id)
    return doc.meta if doc else None


def _extra(event: Event, key: str) -> Any:
    return (event.model_extra or {}).get(key)


def _conductor() -> tuple[int, str | None]:
    """The nearest ancestor process named claude, codex or agy, else the parent."""
    parent = os.getppid()
    pid = parent
    for _ in range(ANCESTORS):
        if pid <= 1:
            break
        found = _ps(pid)
        if found is None:
            break
        ppid, command = found
        name = Path(command).name
        if name in AGENTS:
            return pid, name
        pid = ppid
    return parent, None


def _ps(pid: int) -> tuple[int, str] | None:
    try:
        result = subprocess.run(
            ["ps", "-o", "ppid=,comm=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    fields = result.stdout.strip().split(None, 1)
    if result.returncode != 0 or len(fields) != 2 or not fields[0].isdigit():
        return None
    return int(fields[0]), fields[1].strip()
