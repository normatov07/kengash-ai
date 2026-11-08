"""The loop lease commands: claim, release and status (SP11 spec §4.4 to 4.8)."""

from dataclasses import dataclass
from datetime import datetime

from kengash_ai import settings
from kengash_ai.model import UserError, utc_now
from kengash_ai.ops import conductors, leases, queue, records, relay, waiting, watch
from kengash_ai.ops.conductors import Conductor
from kengash_ai.store.paths import StorePaths


@dataclass
class LeaseView:
    """A live lease as the CLI and the UI show it."""

    pid: int
    agent: str
    project: str | None
    scope: str
    started: datetime
    seen: datetime
    mine: bool  # held by the conductor asking
    line: str  # `loop running: …`, or `this session holds the loop on <scope>`


@dataclass
class Claimed:
    scope: str
    new: bool  # False: the conductor's own lease, refreshed
    watch: str = ""  # a new loop's dashboard tab, or the command to open it (SP13)


@dataclass
class Released:
    scope: str | None  # None: this conductor held no lease


@dataclass
class LoopStatus:
    leases: list[LeaseView]
    loop_start: str


def views(paths: StorePaths, me: Conductor | None) -> list[LeaseView]:
    """Every live lease, the most recently seen first; `mine` against `me`."""
    now = utc_now()
    found: list[LeaseView] = []
    for lease in leases.live(paths):
        mine = me is not None and lease.pid == me.pid
        scope = leases.scope_name(lease.project)
        line = (
            f"this session holds the loop on {scope}"
            if mine
            else f"loop running: {leases.describe(lease, now)}"
        )
        found.append(
            LeaseView(
                lease.pid, lease.agent, lease.project, scope, lease.started, lease.seen, mine, line
            )
        )
    return found


def claim(project: str | None, *, take_over: bool = False) -> Claimed:
    """Take the loop over `project` (None: every project) for the calling conductor."""
    paths = StorePaths.default()
    new = leases.claim(paths, project, conductors.conductor(), take_over=take_over)
    relay.note_claim(paths, project)
    shown = watch.open_dashboard(paths, project) if new else ""
    return Claimed(leases.scope_name(project), new, shown)


def release(*, force: bool = False) -> Released:
    """End the calling conductor's lease; without `force`, refused while `next` would list
    runnable tickets in its scope, or while its ready tickets wait for a slot a live worker
    holds, so tickets added as a loop winds down are never left."""
    paths = StorePaths.default()
    me = conductors.conductor()
    with leases.guarded(paths):
        own = leases.own_lease(paths, me)
        if own is None:
            return Released(None)
        if not force:
            runnable = queue.compute(paths, own.project).runnable
            if runnable:
                raise UserError(f"not released: {len(runnable)} runnable; run: kengash next")
            waiting_now = waiting.slot_wait(paths, records.scope(paths, own.project))
            if waiting_now:
                raise UserError(
                    f"not released: {waiting_now} ready, waiting for a slot; run: kengash wait"
                )
        leases.ended(paths, own, "released")
    relay.note_release(paths, own.project)
    return Released(leases.scope_name(own.project))


def status(project: str | None) -> LoopStatus:
    """Live leases that overlap `project` (all of them for None) and its `loop_start`."""
    paths = StorePaths.default()
    found = [
        view
        for view in views(paths, conductors.conductor())
        if leases.overlaps(view.project, project)
    ]
    return LoopStatus(found, settings.load(paths, project).loop_start)
