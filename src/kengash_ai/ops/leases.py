"""Loop leases: at most one live loop covers a project (SP11 spec §4).

A lease names the conductor running a loop over one project or every project. It is live
while its process runs under the name it had at claim time and was seen within
LOOP_STALE_S; `wait` and `next` refresh it. Writes happen under `locks/loops.lock`, so a
claim and a release are ordered."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from kengash_ai import journal
from kengash_ai.model import Event, LoopBusy, LoopLease, utc_now
from kengash_ai.ops import lifecycle
from kengash_ai.ops.conductors import Conductor, process_name
from kengash_ai.store import runtime
from kengash_ai.store.locks import locked
from kengash_ai.store.paths import StorePaths

LOOP_STALE_S = 3600  # a conductor silent this long may be taken over
LOCK = "loops.lock"


def scope_name(project: str | None) -> str:
    """How messages name a lease's scope."""
    return project or "all projects"


def overlaps(a: str | None, b: str | None) -> bool:
    """Two scopes share a project: either covers every project, or both name the same."""
    return a is None or b is None or a == b


def is_live(lease: LoopLease, now: datetime) -> bool:
    """Seen within LOOP_STALE_S, and its process still runs under the recorded name."""
    if (now - lease.seen).total_seconds() >= LOOP_STALE_S:
        return False
    if not lifecycle.pid_alive(lease.pid):
        return False
    return not lease.command or process_name(lease.pid) == lease.command


def live(paths: StorePaths) -> list[LoopLease]:
    """Every live lease, the most recently seen first; writes nothing."""
    now = utc_now()
    found = [lease for lease in runtime.load_leases(paths) if is_live(lease, now)]
    return sorted(found, key=lambda lease: lease.seen, reverse=True)


def describe(lease: LoopLease, now: datetime) -> str:
    """`<agent> pid <pid> on <scope>, seen <age>`."""
    seconds = (now - lease.seen).total_seconds()
    age = "just now" if seconds < 60 else f"{int(seconds // 60)} min ago"
    return f"{lease.agent} pid {lease.pid} on {scope_name(lease.project)}, seen {age}"


@contextmanager
def guarded(paths: StorePaths) -> Iterator[None]:
    """Hold the lease lock: claims, releases and refreshes never interleave."""
    with locked(paths.locks / LOCK):
        yield


def check(paths: StorePaths, project: str | None, me: Conductor) -> None:
    """Raise LoopBusy when another conductor's live lease overlaps `project`."""
    others = _others(paths, project, me, utc_now())
    if others:
        raise LoopBusy(f"loop running: {describe(others[0], utc_now())}")


def claim(
    paths: StorePaths, project: str | None, me: Conductor, *, take_over: bool = False
) -> bool:
    """Take or refresh `me`'s lease over `project`; True when it is new or rescoped (and
    journaled `loop.started`). Leases that are not live go first, journaled `gone`; another
    conductor's live overlapping lease raises LoopBusy, or with `take_over` is removed and
    journaled `taken_over`."""
    with guarded(paths):
        now = utc_now()
        for lease in runtime.load_leases(paths):
            if lease.pid != me.pid and not is_live(lease, now):
                ended(paths, lease, "gone")
        others = _others(paths, project, me, now)
        if others and not take_over:
            raise LoopBusy(f"loop running: {describe(others[0], now)}")
        for lease in others:
            ended(paths, lease, "taken_over")
        own = _own(paths, me)
        same = own is not None and own.project == project
        started = own.started if own is not None and same else now
        lease = LoopLease(
            pid=me.pid,
            agent=me.agent,
            command=me.command,
            project=project,
            started=started,
            seen=now,
        )
        runtime.save_lease(paths, lease)
        if not same:
            event = {"type": "loop.started", "project": project, "pid": me.pid, "agent": me.agent}
            journal.append(paths, Event.model_validate(event))
        return not same


def refresh(paths: StorePaths, me: Conductor) -> None:
    """Mark `me`'s lease seen now; nothing happens without one (one taken over stays gone)."""
    with guarded(paths):
        own = _own(paths, me)
        if own is not None:
            runtime.save_lease(paths, own.model_copy(update={"seen": utc_now()}))


def own_lease(paths: StorePaths, me: Conductor) -> LoopLease | None:
    """`me`'s lease, if it holds one."""
    return _own(paths, me)


def ended(paths: StorePaths, lease: LoopLease, reason: str) -> None:
    """Drop `lease` and journal `loop.ended` with `reason`; the caller holds the lock."""
    runtime.drop_lease(paths, lease.pid)
    _ended(paths, lease, reason)


def _own(paths: StorePaths, me: Conductor) -> LoopLease | None:
    """The lease on `me`'s pid, unless that pid belonged to another program then."""
    lease = runtime.load_lease(paths, me.pid)
    if lease is None or (lease.command and me.command and lease.command != me.command):
        return None
    return lease


def _others(
    paths: StorePaths, project: str | None, me: Conductor, now: datetime
) -> list[LoopLease]:
    """Other conductors' live leases that overlap `project`, the most recently seen first."""
    found = [
        lease
        for lease in runtime.load_leases(paths)
        if lease.pid != me.pid and overlaps(lease.project, project) and is_live(lease, now)
    ]
    return sorted(found, key=lambda lease: lease.seen, reverse=True)


def _ended(paths: StorePaths, lease: LoopLease, reason: str) -> None:
    event = {
        "type": "loop.ended",
        "project": lease.project,
        "pid": lease.pid,
        "agent": lease.agent,
        "reason": reason,
    }
    journal.append(paths, Event.model_validate(event))
