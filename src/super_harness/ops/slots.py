"""Provider slots per step (SP3 spec decision 17): a claim queues its ticket's first slot,
and workers take freed slots in arrival order."""

from super_harness import scheduler, settings
from super_harness.model import SlotEntry, UserError
from super_harness.store import runtime
from super_harness.store.locks import locked
from super_harness.store.paths import StorePaths
from super_harness.store.registry import load_registry


def limits(paths: StorePaths) -> tuple[scheduler.Limits, dict[str, scheduler.Limits]]:
    """The defaults scope's limits and each project's; a project with invalid settings
    gets the defaults scope's."""
    machine = _limits(paths, None)
    projects: dict[str, scheduler.Limits] = {}
    for slug in load_registry(paths).projects:
        try:
            projects[slug] = _limits(paths, slug)
        except UserError:
            projects[slug] = machine
    return machine, projects


def occupied(paths: StorePaths, *, exclude: str | None = None) -> list[scheduler.Held]:
    """Held and queued slots, except those of ticket `exclude`."""
    table = runtime.load_slots(paths)
    return [
        scheduler.Held(entry.project, entry.provider)
        for entry in (*table.held, *table.waiting)
        if entry.ticket != exclude
    ]


def queue_slot(paths: StorePaths, entry: SlotEntry) -> None:
    """Queue a slot for `entry.ticket` unless it already holds or waits for one."""
    with locked(paths.locks / "slots.lock"):
        table = runtime.load_slots(paths)
        if any(slot.ticket == entry.ticket for slot in (*table.held, *table.waiting)):
            return
        table.waiting.append(entry)
        runtime.save_slots(paths, table)


def reserve(paths: StorePaths, entry: SlotEntry) -> bool:
    """Queue `entry` when one more session fits beside every held and queued one (a claim's
    check and queueing happen under one lock, so two conductors cannot overbook)."""
    with locked(paths.locks / "slots.lock"):
        table = runtime.load_slots(paths)
        others = [s for s in (*table.held, *table.waiting) if s.ticket != entry.ticket]
        used = [scheduler.Held(slot.project, slot.provider) for slot in others]
        machine, projects = limits(paths)
        if not scheduler.fits(entry.provider, entry.project, used, machine, projects):
            return False
        if not any(slot.ticket == entry.ticket for slot in (*table.held, *table.waiting)):
            table.waiting.append(entry)
            runtime.save_slots(paths, table)
        return True


def acquire(paths: StorePaths, entry: SlotEntry) -> bool:
    """True when `entry.ticket` holds a slot after the call.

    Its waiter keeps its place in the queue; it is granted once every earlier waiter
    that fits the limits has been granted first.
    """
    with locked(paths.locks / "slots.lock"):
        table = runtime.load_slots(paths)
        if any(slot.ticket == entry.ticket for slot in table.held):
            return True
        place = next((i for i, w in enumerate(table.waiting) if w.ticket == entry.ticket), None)
        if place is None:
            table.waiting.append(entry)
        else:
            since = table.waiting[place].since
            table.waiting[place] = entry.model_copy(update={"since": since})
        machine, projects = limits(paths)
        used = [scheduler.Held(slot.project, slot.provider) for slot in table.held]
        for waiter in table.waiting:
            if not scheduler.fits(waiter.provider, waiter.project, used, machine, projects):
                continue
            if waiter.ticket == entry.ticket:
                table.waiting.remove(waiter)
                table.held.append(waiter)
                runtime.save_slots(paths, table)
                return True
            used.append(scheduler.Held(waiter.project, waiter.provider))
        runtime.save_slots(paths, table)
        return False


def release(paths: StorePaths, ticket_id: str) -> None:
    """Free the ticket's held and queued slots."""
    with locked(paths.locks / "slots.lock"):
        table = runtime.load_slots(paths)
        held = [slot for slot in table.held if slot.ticket != ticket_id]
        waiting = [slot for slot in table.waiting if slot.ticket != ticket_id]
        if (len(held), len(waiting)) != (len(table.held), len(table.waiting)):
            runtime.save_slots(paths, table.model_copy(update={"held": held, "waiting": waiting}))


def _limits(paths: StorePaths, slug: str | None) -> scheduler.Limits:
    resolved = settings.load(paths, slug)
    return scheduler.Limits(resolved.sessions.max, resolved.sessions.per_provider)
