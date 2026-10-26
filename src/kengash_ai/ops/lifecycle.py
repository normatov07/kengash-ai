"""What the engine's use cases share: step statuses and their events, workflow progress
on tickets, and whether a worker is alive."""

import contextlib
import os
from dataclasses import replace

from kengash_ai import workflow
from kengash_ai.model import Doc, Event, Gate, Settings, Ticket, TicketState

DEAD_AFTER_S = 120  # a worker heartbeats every 15 s

EVENT_TYPES = {
    "needs_approval": "ticket.needs_approval",
    "stalled": "ticket.stalled",
    "failed": "ticket.failed",
    "awaiting_merge": "ticket.awaiting_merge",
    "paused": "ticket.paused",
    "merged": "ticket.merged",
}


def step_status(resolved: Settings, step: str) -> str:
    """The sub-status shown while `step` runs (`status.names`)."""
    return f"in_process/{resolved.status.names.get(step, step)}"


def status_event(
    slug: str,
    ticket: Ticket,
    before: str,
    reason: str,
    *,
    by: str = "kengash",
    kind: str | None = None,
) -> Event:
    """The journal event for the status `ticket` just reached; `harness wait` reads it."""
    kind = kind or EVENT_TYPES.get(ticket.sub_status, "ticket.moved")
    data: dict[str, object] = {
        "type": kind,
        "project": slug,
        "ticket": ticket.id,
        "status": ticket.status,
        "loop": ticket.loop,
        "loop_max": ticket.loop_max,
        "reason": reason,
        "by": by,
    }
    if kind == "ticket.moved":
        data |= {"from": before, "to": ticket.status, "why": reason}
    return Event.model_validate(data)


def pid_alive(pid: int) -> bool:
    """True while `pid` runs; a child of this process that exited is reaped first."""
    with contextlib.suppress(ChildProcessError):
        os.waitpid(pid, os.WNOHANG)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def progress_for(resolved: Settings, ticket: Ticket, state: TicketState) -> workflow.Progress:
    return replace(
        progress_of(resolved, ticket), streaks=state.streaks, plan_rounds=state.plan_rounds
    )


def apply_progress(
    resolved: Settings, doc: Doc[Ticket], state: TicketState, progress: workflow.Progress
) -> None:
    """Store a routed progress on the ticket and its engine state."""
    ticket = doc.meta
    ticket.step = progress.step
    ticket.loop = progress.loop
    ticket.loop_max = progress.loop_max
    if progress.tokens_max != (ticket.tokens_max or resolved.tokens.per_ticket_max):
        ticket.tokens_max = progress.tokens_max
    state.streaks = {step: dict(counts) for step, counts in progress.streaks.items()}
    state.plan_rounds = progress.plan_rounds


def progress_of(resolved: Settings, ticket: Ticket) -> workflow.Progress:
    """The ticket's place in its workflow; a ticket that never ran starts at the first step."""
    hitl = ticket.gate is Gate.hitl
    first = workflow.first_step(resolved, ticket.workflow, hitl=hitl)
    return workflow.Progress(
        workflow=ticket.workflow,
        hitl=hitl,
        step=ticket.step or first,
        loop=ticket.loop,
        loop_max=ticket.loop_max,
        tokens=ticket.tokens,
        tokens_max=ticket.tokens_max or resolved.tokens.per_ticket_max,
    )
