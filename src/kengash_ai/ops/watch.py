"""Watching workers (SP13 spec §3): a viewer tab per worker and a dashboard per loop,
opened in the user's terminal; nothing here runs a model or fails its caller."""

import os
import shlex
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from kengash_ai import journal, settings
from kengash_ai.model import Event, KengashError, Settings, UserError, utc_now
from kengash_ai.ops import (
    activity,
    changes,
    jobs,
    leases,
    progress,
    queue,
    records,
    skills,
    terminals,
    viewers,
)
from kengash_ai.ops.workspace import open_gates
from kengash_ai.store import runtime
from kengash_ai.store.paths import StorePaths

FEED_MAX = 12  # the dashboard's latest actions across every worker
REASON_MAX = 120  # a gate's reason on the dashboard; the full line is in `kengash status`
ACTIONS = {
    "needs_approval": "kengash approve {id}",
    "stalled": "kengash approve {id}",
    "failed": "kengash run {id}",
    "awaiting_merge": "kengash merge {id}",
}


@dataclass
class GateRow:
    """A ticket waiting on the user, and the command that acts on it."""

    id: str
    project: str
    status: str
    title: str
    reason: str
    action: str


@dataclass
class Board:
    """The dashboard (SP13 spec §3.4), read without side effects."""

    loops: list[str] = field(default_factory=list)
    slots: dict[str, tuple[int, int]] = field(default_factory=dict)  # CLI → (used, limit)
    total: tuple[int, int] = (0, 0)
    tokens_today: dict[str, int] = field(default_factory=dict)  # CLI → tokens
    workers: list[progress.Progress] = field(default_factory=list)
    gates: list[GateRow] = field(default_factory=list)
    feed: list[tuple[str, activity.Activity]] = field(default_factory=list)  # (ticket, action)
    stuck: list[queue.Stuck] = field(default_factory=list)  # SP18 spec §3.8


def disabled(env: Mapping[str, str] | None = None) -> bool:
    """Tabs and notifications are off for this process (`KENGASH_WATCH=off`)."""
    return terminals.disabled(env if env is not None else os.environ)


def cli_name() -> str:
    """How a tab reaches this CLI: `kengash` when it is first on PATH, else its path."""
    return skills.invoked_name(sys.argv[0])


def open_ticket(paths: StorePaths, slug: str, ticket_id: str) -> str:
    """Open the ticket's worker tab unless one is open; what the user watches it with."""
    command = [cli_name(), "logs", ticket_id, "--watch"]
    # with no tab, `-f`: it ends when the ticket stops, so an agent's background task ends too
    printed = [cli_name(), "logs", ticket_id, "-f"]
    return _open(paths, slug, f"ticket-{ticket_id}", f"kg {ticket_id}", command, printed)


def open_dashboard(paths: StorePaths, project: str | None) -> str:
    """Open the loop's dashboard tab unless one is open for this scope."""
    command = [cli_name(), "watch", *(["-p", project] if project else [])]
    title = f"kg watch {project}" if project else "kg watch"
    return _open(paths, project, f"watch-{project or 'all'}", title, command)


def attach_tab(ticket_id: str, *, role: str | None, project: str | None) -> str:
    """Open a tab on a role's own session in the ticket's worktree, so the user talks to
    that agent; refused while a worker drives the session (SP13 spec §3.6)."""
    paths = StorePaths.default()
    if jobs.alive(paths, ticket_id) is not None:
        raise UserError(f"a worker is running {ticket_id}; attach once it stops")
    found = changes.attach_command(ticket_id, role=role, project=project)
    title = f"kg {ticket_id} {found.role}"
    key = f"attach-{ticket_id}-{found.role}"
    return _open(paths, found.project, key, title, ["sh", "-c", found.command])


def _open(
    paths: StorePaths,
    slug: str | None,
    key: str,
    title: str,
    command: list[str],
    fallback: list[str] | None = None,
) -> str:
    """Open `command` in a tab titled `title`; else the command to run instead."""
    printed = shlex.join(fallback or command)
    if disabled():
        return printed
    try:
        resolved = settings.load(paths, slug)
    except (KengashError, UserError):
        return printed
    if resolved.watch.tabs == "off":
        return printed
    terminal = terminals.detect(os.environ, resolved.watch.terminal)
    if terminal is None:
        return printed
    shown = f"{terminal.name} tab {title}"
    if not viewers.claim(paths, key):
        return shown  # its viewer runs, or its tab is opening
    if terminals.open_tab(terminal, title, command, cwd=Path.cwd()):
        return shown
    viewers.unclaim(paths, key)
    return printed


@contextmanager
def viewing(key: str) -> Iterator[None]:
    """This process is `key`'s viewer for the block, so no second tab opens for it."""
    paths = StorePaths.default()
    viewers.register(paths, key)
    try:
        yield
    finally:
        viewers.release(paths, key)


def snapshot(project: str | None) -> Board:
    """`board` over one project, or every project, of the user's store."""
    paths = StorePaths.default()
    return board(paths, records.scope(paths, project))


def board(paths: StorePaths, slugs: list[str], *, feed_max: int = FEED_MAX) -> Board:
    """Everything the dashboard shows for these projects; the journal is read once."""
    now = utc_now()
    defaults = _settings(paths)
    gated = [(slug, gate) for slug in slugs for gate in open_gates(paths, slug)]
    docs = {slug: records.project_tickets(paths, slug) for slug in slugs}
    days = [docs[slug][g.id].meta.updated.date() for slug, g in gated if g.id in docs[slug]]
    events = list(journal.read(paths, since=min([now.date(), *days])))
    held = runtime.load_slots(paths).held
    limits = defaults.sessions.per_provider
    workers = progress.running(paths, slugs)
    feed = [
        (worker.id, item)
        for worker in workers
        for item in activity.ticket(paths, worker.project, worker.id, events=events)
        if item.kind != "status"
    ]
    floor = now.replace(year=1)
    feed.sort(key=lambda pair: pair[1].ts or floor)
    return Board(
        loops=[leases.describe(lease, now) for lease in leases.live(paths)],
        slots={cli: (sum(h.provider == cli for h in held), limits[cli]) for cli in sorted(limits)},
        total=(len(held), defaults.sessions.max),
        tokens_today=_tokens_today(events, now.date().isoformat()),
        workers=workers,
        gates=[
            _gate_row(slug, gate.id, gate.sub_status, gate.title, events) for slug, gate in gated
        ],
        feed=feed[-feed_max:],
        stuck=[item for slug in slugs for item in queue.stuck(docs[slug], slug)],
    )


def lines(found: Board) -> list[str]:
    """The board as plain text: `kengash watch --once`, and any screen without colour."""
    out = [f"loops: {'; '.join(found.loops)}" if found.loops else "loops: no loop running"]
    slots = [f"{cli} {used}/{limit}" for cli, (used, limit) in found.slots.items()]
    slots.append(f"total {found.total[0]}/{found.total[1]}")
    if found.tokens_today:
        today = ", ".join(f"{cli} {_k(n)}" for cli, n in sorted(found.tokens_today.items()))
        slots.append(f"tokens today: {today}")
    out.append("slots: " + " · ".join(slots))
    out.append("running:" if found.workers else "running: nothing")
    out += ["  " + " · ".join(worker_parts(p)) for p in found.workers]
    out.append("needs you:" if found.gates else "needs you: nothing")
    out += [f"  {g.id} {g.status}: {g.reason} → {g.action}" for g in found.gates]
    out += [f"waiting on {s.id} ({s.status}): {s.behind} tickets behind it" for s in found.stuck]
    if found.feed:
        out.append("latest:")
        out += [f"  {_clock(item)} {ticket} {item.text}" for ticket, item in found.feed]
    return out


def worker_parts(p: progress.Progress) -> list[str]:
    """A worker's progress parts with its project and its tokens of the cap."""
    found = progress.parts(p, project=True)
    if p.tokens_max:
        found.insert(3, f"{_k(p.tokens)}/{_k(p.tokens_max)} tokens")
    return found


def _settings(paths: StorePaths) -> Settings:
    try:
        return settings.load(paths)
    except (KengashError, UserError):
        return Settings()


def _tokens_today(events: list[Event], day: str) -> dict[str, int]:
    found: dict[str, int] = {}
    for event in events:
        extra = event.model_extra or {}
        if event.type != "step.end" or event.ts.date().isoformat() != day:
            continue
        tokens = extra.get("tokens") or {}
        used = int(tokens.get("in", 0)) + int(tokens.get("out", 0))
        cli = str(extra.get("provider") or "")
        if cli and used:
            found[cli] = found.get(cli, 0) + used
    return found


def _gate_row(slug: str, ticket_id: str, status: str, title: str, events: list[Event]) -> GateRow:
    kind = f"ticket.{status}"
    reasons = [
        str((e.model_extra or {}).get("reason") or "")
        for e in events
        if e.type == kind and e.ticket == ticket_id and e.project == slug
    ]
    reason = reasons[-1].splitlines()[0] if reasons and reasons[-1] else status.replace("_", " ")
    if len(reason) > REASON_MAX:
        reason = reason[: REASON_MAX - 1] + "…"
    action = ACTIONS.get(status, "kengash status").format(id=ticket_id)
    return GateRow(ticket_id, slug, status, title, reason, action)


def _k(tokens: int) -> str:
    return f"{round(tokens / 1000)}k"


def _clock(item: activity.Activity) -> str:
    return item.ts.astimezone().strftime("%H:%M:%S") if item.ts else "--:--:--"
