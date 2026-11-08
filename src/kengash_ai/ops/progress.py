"""Running tickets at a glance: step, CLI, elapsed, last activity, worktree changes, last
action; read without side effects (SP12 spec §4.2)."""

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from kengash_ai import gitops, journal, settings
from kengash_ai.model import Folder, KengashError, Ticket, TicketState, utc_now
from kengash_ai.ops import activity, lifecycle, records
from kengash_ai.store import runtime
from kengash_ai.store.paths import StorePaths

QUIET_S = 600  # no log or worktree write this long marks a step quiet (nothing is killed)
CACHE_S = 60  # how long one worktree's `git status` answer is reused
_changed: dict[Path, tuple[float, list[str]]] = {}


@dataclass
class Progress:
    id: str
    project: str
    step: str
    provider: str
    model: str
    elapsed_s: float
    alive: bool
    active_s: float | None
    action: str
    changed: int
    quiet: bool
    tokens: int = 0  # used by the ticket so far (SP13)
    tokens_max: int = 0  # the ticket's cap


def running(paths: StorePaths, slugs: list[str]) -> list[Progress]:
    """One Progress per ticket in scope that a worker is busy with."""
    found: list[Progress] = []
    starts = _starts(paths, slugs)
    now = utc_now()
    for slug in slugs:
        for doc in records.project_tickets(paths, slug).values():
            ticket = doc.meta
            if ticket.folder is not Folder.in_process or not activity.running_status(ticket.status):
                continue
            state = runtime.load_ticket_state(paths, ticket.id)
            run = state.running
            worktree = paths.worktree(slug, ticket.id)
            changed, newest = _worktree(worktree)
            log_time = _mtime(run.log) if run is not None else None
            times = [t for t in (log_time, newest) if t is not None]
            active = (now.timestamp() - max(times)) if times else None
            started = starts.get(ticket.id) or ticket.updated
            found.append(
                Progress(
                    id=ticket.id,
                    project=slug,
                    step=ticket.step or "",
                    provider=run.provider if run else "",
                    model=(run.model or "default") if run else "",
                    elapsed_s=max((now - started).total_seconds(), 0),
                    alive=_alive(paths, ticket.id, now),
                    active_s=active,
                    action=_waiting(ticket, state) or (_action(run.log, worktree) if run else ""),
                    changed=changed,
                    quiet=not _waiting(ticket, state) and active is not None and active >= QUIET_S,
                    tokens=ticket.tokens,
                    tokens_max=ticket.tokens_max or _cap(paths, slug),
                )
            )
    return found


def snapshot(project: str | None) -> list[Progress]:
    """`running` over one project, or every project, of the user's store."""
    paths = StorePaths.default()
    return running(paths, records.scope(paths, project))


def short(found: list[Progress]) -> str:
    """One line for a status bar: `kg: <N> running · <id> <step>→<provider> <elapsed>
    <action>`, or `kg: nothing running`."""
    if not found:
        return "kg: nothing running"
    first = found[0]
    who = f"{first.step}→{first.provider}" if first.provider else _between(first)
    head = f"{first.id} {who} {_span(first.elapsed_s)}"
    return f"kg: {len(found)} running · {head} {first.action}".rstrip()


def line(p: Progress) -> str:
    """`<id> <step>→<provider>/<model> <elapsed> · active <age> ago · <N> files changed ·
    <action>`, then ` · quiet` and ` · worker gone` when they apply."""
    return " · ".join(parts(p))


def parts(p: Progress, *, project: bool = False) -> list[str]:
    """`line`'s parts; `project` names the ticket's project after its id (the dashboard)."""
    who = f"{p.step}→{p.provider}/{p.model}" if p.provider else _between(p)
    head = f"{p.id} {p.project} {who}" if project else f"{p.id} {who}"
    found = [f"{head} {_span(p.elapsed_s)}"]
    found.append(f"active {_span(p.active_s)} ago" if p.active_s is not None else "no activity yet")
    found.append(f"{p.changed} files changed")
    if p.action:
        found.append(p.action)
    if p.quiet:
        found.append("quiet")
    if not p.alive:
        found.append("worker gone")
    return found


def forget() -> None:
    """Drop the cached worktree answers (tests, and a UI reload after a merge)."""
    _changed.clear()


def _starts(paths: StorePaths, slugs: list[str]) -> dict[str, datetime]:
    """Each ticket's last `step.start` time."""
    found: dict[str, datetime] = {}
    since = (utc_now() - timedelta(days=1)).date()  # a step may span midnight
    for event in journal.read(paths, since=since):
        if event.type == "step.start" and event.project in slugs and event.ticket:
            found[event.ticket] = event.ts
    return found


def _cap(paths: StorePaths, slug: str) -> int:
    try:
        return settings.load(paths, slug).tokens.per_ticket_max
    except KengashError:
        return 0


def _alive(paths: StorePaths, ticket_id: str, now: datetime) -> bool:
    record = runtime.load_worker(paths, ticket_id)
    if record is None or not lifecycle.pid_alive(record.pid):
        return False
    return (now - record.heartbeat).total_seconds() < lifecycle.DEAD_AFTER_S


def _waiting(ticket: Ticket, state: TicketState) -> str:
    """What a job waiting for another ticket's paths is doing; it is never quiet (SP16)."""
    if ticket.sub_status != "waiting_paths":
        return ""
    return f"waiting for {state.waiting_on or 'another ticket'} to finish editing its paths"


def _worktree(worktree: Path) -> tuple[int, float | None]:
    """Changed files (one `git status` per worktree per CACHE_S) and the newest write
    among them."""
    if not worktree.is_dir():
        return 0, None
    cached = _changed.get(worktree)
    if cached is None or time.monotonic() - cached[0] > CACHE_S:
        cached = (time.monotonic(), gitops.changed_files(worktree))
        _changed[worktree] = cached
    files = cached[1]
    times = [t for name in files if (t := _mtime(worktree / name)) is not None]
    return len(files), max(times) if times else None


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _action(log: Path, worktree: Path) -> str:
    if not log.is_file():
        return ""
    tail = activity._read(log)
    found = activity.parse(tail.text, tail.stamps, root=worktree)
    return found[-1].text if found else ""


def _between(p: Progress) -> str:
    """The step of a worker that runs no CLI right now: committing, routing or waiting."""
    return f"{p.step} (between calls)"


def _span(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m"
