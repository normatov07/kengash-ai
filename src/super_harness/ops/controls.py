"""Claim tickets and steer running ones (SP3 spec decisions 8, 18, 21, 22)."""

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from super_harness import gitops, journal, scheduler, settings, workflow
from super_harness.model import (
    Doc,
    Event,
    Folder,
    NeedsSetup,
    ProviderStatus,
    SlotEntry,
    Ticket,
    UserError,
    WorkerRecord,
    utc_now,
)
from super_harness.ops import agents, jobs, lifecycle, merging, records, slots, steps
from super_harness.store import documents, runtime, storegit
from super_harness.store.locks import locked
from super_harness.store.paths import StorePaths
from super_harness.store.registry import load_registry

RESUMABLE = ("in_queue/ready", "in_process/failed", "in_process/stalled", "in_process/paused")
NO_SLOT = ("shell", "user")
SANDBOXED = (
    "harness run cannot start workers inside a network-less codex sandbox; "
    "run it outside the sandbox"
)


@dataclass
class Started:
    id: str
    project: str
    step: str
    provider: str


@dataclass
class RunResult:
    started: list[Started] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)


@dataclass
class Approved:
    id: str
    project: str
    status: str


@dataclass
class Parked:
    id: str
    project: str
    deferred: bool


@dataclass
class Paused:
    project: str | None
    running: int


@dataclass
class Resumed:
    started: list[str]


@dataclass
class _Skip:
    reason: str
    setup: bool = False


def run_tickets(
    ids: Sequence[str], *, steps: int | None = None, project: str | None = None, by: str
) -> RunResult:
    """Claim each ticket and start its worker; a ticket that cannot start says why."""
    if os.environ.get("CODEX_SANDBOX_NETWORK_DISABLED") == "1":
        raise NeedsSetup(SANDBOXED)
    paths = StorePaths.default()
    detect = agents.detector(paths)
    result = RunResult()
    setup: str | None = None
    for ticket_id in ids:
        try:
            slug, _ = records.locate_ticket(paths, ticket_id, project)
        except UserError as exc:
            result.skipped[ticket_id] = str(exc)
            continue
        outcome = _claim(paths, slug, ticket_id, steps=steps, by=by, detect=detect)
        if isinstance(outcome, Started):
            result.started.append(outcome)
            continue
        result.skipped[ticket_id] = outcome.reason
        if outcome.setup and setup is None:
            setup = outcome.reason
    if result.started:
        storegit.commit_store(paths, f"harness: run {' '.join(s.id for s in result.started)}")
    elif setup is not None:
        raise NeedsSetup(setup)
    return result


def spawn_worker(paths: StorePaths, slug: str, ticket_id: str, steps: int | None) -> int:
    """Start the ticket's worker detached, logging to runtime/logs/<id>.log."""
    args = ["ticket", ticket_id, *(["--steps", str(steps)] if steps else []), "--project", slug]
    return jobs.spawn(paths, args, ticket_id)


def approve_ticket(
    ticket_id: str, *, loops: int | None, tokens: int | None, project: str | None, by: str
) -> Approved:
    """Open an approval gate: more loops, more tokens, or the approve step passed."""
    paths = StorePaths.default()
    slug, _ = records.locate_ticket(paths, ticket_id, project)
    resolved = settings.load(paths, slug)
    with locked(_lock(paths, slug)):
        doc = _load(paths, slug, ticket_id)
        ticket = doc.meta
        state = runtime.load_ticket_state(paths, ticket_id)
        approval = state.approval
        if ticket.status != workflow.NEEDS_APPROVAL or approval is None:
            raise UserError(f"{ticket_id} is not waiting for approval")
        progress = lifecycle.progress_for(resolved, ticket, state)
        routed = workflow.approve(resolved, progress, approval, loops=loops, tokens=tokens)
        lifecycle.apply_progress(resolved, doc, state, routed.progress)
        state.approval = None
        decision = routed.decision
        before = ticket.status
        events: list[Event] = []
        restart = isinstance(decision, workflow.Run)
        if isinstance(decision, workflow.Run):
            ticket.status = lifecycle.step_status(resolved, decision.step)
        elif isinstance(decision, workflow.Halt):
            ticket.status = decision.status
            state.approval = decision.approval
            events.append(lifecycle.status_event(slug, ticket, before, decision.reason))
        else:
            ticket.status = workflow.AWAITING_MERGE
            events.append(lifecycle.status_event(slug, ticket, before, "every step passed"))
        ticket.updated = utc_now()
        documents.save_ticket(paths.project(slug), doc)
        runtime.save_ticket_state(paths, ticket_id, state)
        approved = _event(
            "ticket.approved",
            slug,
            ticket,
            approval=approval,
            loops=loops,
            tokens=tokens,
            status=ticket.status,
            by=by,
        )
        if restart:
            _start_worker(paths, slug, ticket, steps=None)
        records.record(paths, f"harness: approve {ticket_id}", approved, *events)
    if isinstance(decision, workflow.Merge):
        return Approved(ticket_id, slug, merging.merge_if_clean(paths, slug, ticket_id, by=by))
    return Approved(ticket_id, slug, ticket.status)


def park_ticket(ticket_id: str, why: str, *, project: str | None, by: str) -> Parked:
    """Park a ticket now, or after its running step."""
    reason = records.one_line(why, "why")
    paths = StorePaths.default()
    slug, _ = records.locate_ticket(paths, ticket_id, project)
    with locked(_lock(paths, slug)):
        if _live(paths, ticket_id):
            runtime.set_park(paths, ticket_id, on=True)
            return Parked(ticket_id, slug, deferred=True)
        doc = _load(paths, slug, ticket_id)
        ticket = doc.meta
        if ticket.folder is Folder.done:
            raise UserError(f"{ticket_id} is {ticket.status}; only open tickets park")
        before = ticket.status
        ticket.status = "in_queue/parked"
        ticket.updated = utc_now()
        documents.save_ticket(paths.project(slug), doc)
        slots.release(paths, ticket_id)
        event = lifecycle.status_event(slug, ticket, before, reason, by=by)
        records.record(paths, f"harness: park {ticket_id}", event)
    return Parked(ticket_id, slug, deferred=False)


def stop_ticket(ticket_id: str, *, project: str | None, by: str) -> str:
    """Kill the ticket's worker now, then mark the ticket failed "stopped"."""
    paths = StorePaths.default()
    slug, _ = records.locate_ticket(paths, ticket_id, project)
    if not jobs.end(paths, ticket_id):
        raise UserError(f"{ticket_id} has no running worker")
    return steps.fail_ticket(paths, slug, ticket_id, "stopped", kind="ticket.stopped")


def pause(project: str | None, *, by: str) -> Paused:
    """Start nothing new in scope; running workers finish their step, then pause."""
    paths = StorePaths.default()
    scope = records.scope(paths, project)
    runtime.set_pause(paths, project, on=True)
    running = sum(
        1
        for record in runtime.load_workers(paths)
        if record.project in scope and _live(paths, record.id)
    )
    return Paused(project, running)


def resume(project: str | None, *, by: str) -> Resumed:
    """Clear the pause (every pause when `project` is None) and restart paused tickets."""
    paths = StorePaths.default()
    scope = records.scope(paths, project)
    runtime.set_pause(paths, project, on=False)
    if project is None:
        for slug in load_registry(paths).projects:
            runtime.set_pause(paths, slug, on=False)
    paused = [
        doc.meta.id
        for slug in scope
        for doc in records.project_tickets(paths, slug).values()
        if doc.meta.status == "in_process/paused"
    ]
    if not paused:
        return Resumed([])
    result = run_tickets(sorted(paused), project=project, by=by)
    return Resumed([started.id for started in result.started])


def _claim(
    paths: StorePaths,
    slug: str,
    ticket_id: str,
    *,
    steps: int | None,
    by: str,
    detect: Callable[[str], ProviderStatus],
) -> Started | _Skip:
    """Check the ticket against SP3 spec §7 under the locks, then claim it."""
    entry = load_registry(paths).projects[slug]
    with locked(_lock(paths, slug)):
        doc = _load(paths, slug, ticket_id)
        ticket = doc.meta
        if _live(paths, ticket_id):
            return _Skip("already running")
        if ticket.status not in RESUMABLE:
            return _Skip(f"status {ticket.status}")
        if runtime.pause_state(paths).covers(slug):
            return _Skip("paused")
        for other in records.project_tickets(paths, slug).values():
            meta = other.meta
            busy = meta.folder is Folder.in_process and meta.id != ticket_id
            if busy and scheduler.overlaps(meta.touches, ticket.touches):
                return _Skip(f"touches overlap {meta.id}")
        resolved = settings.load(paths, slug)
        if ticket.workflow not in resolved.workflows:
            return _Skip(f"settings have no workflow {ticket.workflow!r}")
        state = runtime.load_ticket_state(paths, ticket_id)
        if ticket.status == workflow.STALLED:
            # resuming a stalled ticket restarts its stall counting (SP3 spec decision 34)
            state.streaks, state.plan_rounds = {}, 0
        decision = workflow.before(resolved, lifecycle.progress_for(resolved, ticket, state))
        if isinstance(decision.decision, workflow.Run):
            step = decision.decision.step
        elif (
            isinstance(decision.decision, workflow.Halt)
            and decision.decision.approval == "approve_step"
        ):
            step = "approve"
        else:
            halt = decision.decision
            return _Skip(halt.reason if isinstance(halt, workflow.Halt) else "every step passed")
        role = resolved.role_of(step)
        provider = "user"
        if role is not None:
            try:
                provider = agents.pick(resolved, role, detect).provider
            except NeedsSetup as exc:
                return _Skip(str(exc), setup=True)
        if provider not in NO_SLOT:
            slot = SlotEntry(provider=provider, project=slug, ticket=ticket_id, step=step, pid=0)
            if not slots.reserve(paths, slot):
                return _Skip(f"no free {provider} slot")
        branch = f"hrn/{ticket_id}"
        try:
            with locked(paths.locks / f"repo-{slug}.lock"):
                gitops.ensure_worktree(
                    entry.path, paths.worktree(slug, ticket_id), branch, entry.base
                )
        except UserError as exc:
            slots.release(paths, ticket_id)
            return _Skip(str(exc))
        before = ticket.status
        ticket.branch = branch
        ticket.step = step
        ticket.status = lifecycle.step_status(resolved, step)
        events = [_event("ticket.claimed", slug, ticket, step=step, provider=provider, by=by)]
        events[0] = events[0].model_copy(update={"from": before})
        if step == "approve":  # the user's step: no worker until `harness approve`
            ticket.status = workflow.NEEDS_APPROVAL
            state.approval = "approve_step"
            reason = "waiting for the user's approval"
            events.append(lifecycle.status_event(slug, ticket, before, reason))
        ticket.updated = utc_now()
        documents.save_ticket(paths.project(slug), doc)
        runtime.save_ticket_state(paths, ticket_id, state)
        if step != "approve":
            _start_worker(paths, slug, ticket, steps=steps)
        with locked(paths.locks / "claims.lock"):
            claims = runtime.load_claims(paths)
            claims.last[slug] = utc_now()
            runtime.save_claims(paths, claims)
        for event in events:
            journal.append(paths, event)
    return Started(ticket_id, slug, step, provider)


def _start_worker(paths: StorePaths, slug: str, ticket: Ticket, *, steps: int | None) -> None:
    pid = spawn_worker(paths, slug, ticket.id, steps)
    runtime.save_worker(paths, WorkerRecord(id=ticket.id, project=slug, pid=pid, step=ticket.step))


def _live(paths: StorePaths, ticket_id: str) -> bool:
    """A worker record whose process runs and whose heartbeat is fresh."""
    record = runtime.load_worker(paths, ticket_id)
    if record is None:
        return False
    fresh = (utc_now() - record.heartbeat).total_seconds() < lifecycle.DEAD_AFTER_S
    return fresh and lifecycle.pid_alive(record.pid)


def _event(kind: str, slug: str, ticket: Ticket, **fields: object) -> Event:
    data: dict[str, object] = {"type": kind, "project": slug, "ticket": ticket.id, **fields}
    return Event.model_validate(data)


def _lock(paths: StorePaths, slug: str) -> Path:
    return paths.locks / f"{slug}.lock"


def _load(paths: StorePaths, slug: str, ticket_id: str) -> Doc[Ticket]:
    path = documents.find_ticket(paths.project(slug), ticket_id)
    if path is None:
        raise UserError(f"unknown ticket: {ticket_id}")
    return documents.load_ticket(path)
