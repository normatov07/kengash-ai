"""Ticket status changes the engine's use cases share: step statuses and their events."""

from super_harness.model import Event, Settings, Ticket

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
    by: str = "harness",
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
