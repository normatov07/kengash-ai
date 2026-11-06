"""Wait for gates and queued tickets, find dead workers, record conductor pings (SP3 spec
decisions 9, 24, 33); `wait` holds the loop lease (SP11 spec §4.5, §4.9)."""

import time
from dataclasses import dataclass, field
from typing import Any

from kengash_ai import journal
from kengash_ai.model import (
    ConductorPing,
    Event,
    Folder,
    PlanStatus,
    Ticket,
    WorkerRecord,
    utc_now,
)
from kengash_ai.ops import conductors, jobs, leases, lifecycle, records, steps
from kengash_ai.ops.workspace import GATES
from kengash_ai.store import runtime
from kengash_ai.store.paths import StorePaths

WAIT_TYPES = (
    "ticket.needs_approval",
    "ticket.stalled",
    "ticket.failed",
    "ticket.awaiting_merge",
    "ticket.merged",
    "plan.reviewed",
)
NOT_RUNNING = (*GATES, "paused")
READY = "in_queue/ready"


@dataclass
class WaitEvent:
    id: str
    project: str
    status: str
    loop: int
    loop_max: int
    detail: str
    kind: str = "ticket"  # or "plan": status is the verdict, loop the review round


@dataclass
class WaitResult:
    events: list[WaitEvent] = field(default_factory=list)
    idle: bool = False
    timed_out: bool = False


def dead_workers(paths: StorePaths) -> list[WorkerRecord]:
    """Every worker record whose process is gone or whose heartbeat is older than
    DEAD_AFTER_S."""
    dead: list[WorkerRecord] = []
    for record in runtime.load_workers(paths):
        age = (utc_now() - record.heartbeat).total_seconds()
        if age >= lifecycle.DEAD_AFTER_S or not lifecycle.pid_alive(record.pid):
            dead.append(record)
    return dead


def check_workers(paths: StorePaths, *, fix: bool = True) -> list[str]:
    """Ids of the jobs whose worker died; with `fix`, each running ticket fails "worker
    died", and a dead plan-review or compaction job is dropped (its slot freed)."""
    dead = dead_workers(paths)
    if fix:
        for record in dead:
            if record.job == "ticket":
                steps.fail_ticket(paths, record.project, record.id, "worker died")
            else:
                jobs.died(paths, record)
            runtime.drop_worker(paths, record.id)
    return [record.id for record in dead]


def ping(paths: StorePaths, project: str | None, me: conductors.Conductor | None = None) -> None:
    """Record the conductor (`conductors.conductor`): its pid, agent and project filter;
    its loop lease, if it holds one, is seen now."""
    me = me or conductors.conductor()
    runtime.save_ping(paths, ConductorPing(pid=me.pid, agent=me.agent, project=project))
    leases.refresh(paths, me)


def wait(project: str | None, *, timeout: float, poll_s: float = 1.0) -> WaitResult:
    """Block until a ticket in scope needs the conductor or becomes ready; each event is
    reported once. A conductor found by process name holds the scope's loop lease (taking
    it if free); any other caller takes none. Both get LoopBusy (exit 6) while another
    conductor's live lease covers the scope, so two conductors never share events."""
    paths = StorePaths.default()
    slugs = records.scope(paths, project)
    scope = project or "all"
    me = conductors.conductor()
    if me.detected:
        leases.claim(paths, project, me)
    else:
        leases.check(paths, project, me)
    check_workers(paths)
    ping(paths, project, me)
    cursor = runtime.load_cursor(paths, scope)
    if cursor is None:
        cursor = journal.end(paths)  # saved before the scan, so no gate slips between them
        runtime.save_cursor(paths, scope, cursor)
        gates = _open_gates(paths, slugs)
        if gates:
            return WaitResult(events=gates)
    deadline = time.monotonic() + timeout
    held: int | None = None  # live slots last round, while ready tickets wait on them
    while True:
        if me.detected and leases.own_lease(paths, me) is None:
            # taken over while polling: stop before reading the scope's events (SP11 §4.9)
            leases.check(paths, project, me)
            leases.claim(paths, project, me)  # nobody else holds it: take the scope back
        # checked before the read: a worker journals its last event before it exits, so once
        # nothing runs, every event that ended the work is already in the journal
        running = _running(paths, slugs)
        events, cursor = journal.read_after(paths, cursor)
        runtime.save_cursor(paths, scope, cursor)
        found = [_wait_event(paths, event) for event in events if _wanted(event, slugs)]
        if found:
            return WaitResult(events=found)
        if not running:
            slots = _live_slots(paths)
            if not (slots and _ready(paths, slugs)) or (held is not None and slots < held):
                return WaitResult(idle=True)  # nothing to wait for, or a slot freed: run `next`
            held = slots
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return WaitResult(timed_out=True)
        time.sleep(min(poll_s, remaining))
        check_workers(paths)


def slot_wait(paths: StorePaths, slugs: list[str]) -> int:
    """Ready tickets in scope (outside paused projects) while a live worker of any project
    holds a slot: they start once a slot frees, so a loop over them must not end (slots are
    machine-wide; SP11 spec §4.6, §4.9)."""
    return _ready(paths, slugs) if _live_slots(paths) else 0


def _ready(paths: StorePaths, slugs: list[str]) -> int:
    pause = runtime.pause_state(paths)
    return sum(
        doc.meta.status == READY
        for slug in slugs
        if not pause.covers(slug)
        for doc in records.project_tickets(paths, slug).values()
    )


def _live_slots(paths: StorePaths) -> int:
    return sum(lifecycle.pid_alive(entry.pid) for entry in runtime.load_slots(paths).held)


def _wanted(event: Event, slugs: list[str]) -> bool:
    if event.project not in slugs:
        return False
    if event.type in WAIT_TYPES:
        return True
    if event.type in ("ticket.created", "ticket.recirculated"):  # added, or re-queued by a
        return bool(_extra(event, "status") == READY)  # merge conflict
    to = str(_extra(event, "to"))
    return event.type == "ticket.moved" and (to.startswith("done/") or to == READY)


def _wait_event(paths: StorePaths, event: Event) -> WaitEvent:
    if event.type == "plan.reviewed":
        return WaitEvent(
            id=str(event.plan),
            project=str(event.project),
            status=str(_extra(event, "verdict")),
            loop=int(_extra(event, "round") or 0),
            loop_max=int(_extra(event, "max") or 0),
            detail=str(_extra(event, "summary") or ""),
            kind="plan",
        )
    status = _extra(event, "status") or _extra(event, "to")
    loop, loop_max = _extra(event, "loop"), _extra(event, "loop_max")
    if loop is None or loop_max is None:
        ticket = _ticket(paths, str(event.project), str(event.ticket))
        loop, loop_max = (ticket.loop, ticket.loop_max) if ticket else (0, 0)
    detail = _extra(event, "reason") or _extra(event, "why") or ""
    if status == READY:  # added ready, or unblocked by a merge: the conductor starts it
        ticket = _ticket(paths, str(event.project), str(event.ticket))
        status, detail = "queued", _extra(event, "title") or (ticket.title if ticket else "")
    return WaitEvent(
        id=str(event.ticket),
        project=str(event.project),
        status=str(status),
        loop=int(loop),
        loop_max=int(loop_max),
        detail=str(detail),
    )


def _open_gates(paths: StorePaths, slugs: list[str]) -> list[WaitEvent]:
    """Tickets at a gate, and reviewed plans waiting for the user's approval."""
    gates = [
        WaitEvent(
            doc.meta.id, slug, doc.meta.status, doc.meta.loop, doc.meta.loop_max, doc.meta.title
        )
        for slug in slugs
        for doc in records.project_tickets(paths, slug).values()
        if doc.meta.folder is Folder.in_process and doc.meta.sub_status in GATES
    ]
    for slug in slugs:
        for plan in (doc.meta for doc in records.project_plans(paths, slug).values()):
            review = plan.review
            if plan.status is PlanStatus.in_review and review.verdict is not None:
                detail = f"review {review.verdict}; waiting for the user's approval"
                gates.append(
                    WaitEvent(plan.id, slug, "in_review", review.round, review.max, detail, "plan")
                )
    return gates


def _running(paths: StorePaths, slugs: list[str]) -> bool:
    """A ticket in scope is running a step, or a worker in scope (a ticket's or a plan
    review's) is still alive: one that just saved its ticket at a gate journals it next."""
    working = any(
        record.project in slugs and jobs.alive(paths, record.id) is not None
        for record in runtime.load_workers(paths)
    )
    return working or any(
        doc.meta.folder is Folder.in_process and doc.meta.sub_status not in NOT_RUNNING
        for slug in slugs
        for doc in records.project_tickets(paths, slug).values()
    )


def _ticket(paths: StorePaths, slug: str, ticket_id: str) -> Ticket | None:
    doc = records.project_tickets(paths, slug).get(ticket_id)
    return doc.meta if doc else None


def _extra(event: Event, key: str) -> Any:
    return (event.model_extra or {}).get(key)
