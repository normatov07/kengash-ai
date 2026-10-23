"""Read models for the UI screens (SP5 spec §3): plain dataclasses built from the store,
the runtime files and the journal. Nothing here writes."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from super_harness import __version__, journal, settings
from super_harness.model import (
    STEP_ROLES,
    ConductorPing,
    Doc,
    Event,
    Folder,
    HarnessError,
    JournalCursor,
    Ticket,
    split_cli,
    utc_now,
)
from super_harness.ops import records
from super_harness.ops.workspace import GATES
from super_harness.store import runtime
from super_harness.store.paths import StorePaths
from super_harness.store.registry import load_registry

Window = Literal["today", "7d", "all"]
WAITING = ("waiting_slot", "waiting_quota", "paused")
TAIL = 30
FRESH_PING = timedelta(minutes=10)
COLUMNS = (
    ("in_queue", "In queue"),
    ("plan", "Planning"),
    ("review_plan", "Plan review"),
    ("implement", "Implementing"),
    ("review_code", "Code review"),
    ("security", "Security"),
    ("run_tests", "Tests"),
    ("docs", "Docs"),
    ("waiting", "Waiting"),
    ("needs_you", "Needs you"),
    ("done", "Done"),
)


@dataclass
class Session:
    ticket: str
    project: str
    title: str
    step: str
    status: str
    provider: str
    model: str
    loop: int
    loop_max: int
    since: datetime


@dataclass
class Counts:
    ready: int = 0
    blocked: int = 0
    parked: int = 0
    parallel: int = 0
    serial: int = 0


@dataclass
class Gate:
    ticket: str
    project: str
    status: str
    title: str
    loop: int
    loop_max: int
    reason: str


@dataclass
class Slot:
    provider: str
    used: int
    total: int


@dataclass
class Overview:
    projects: list[str] = field(default_factory=list)
    paused: bool = False  # `harness pause` without a project
    sessions: list[Session] = field(default_factory=list)
    queue: Counts = field(default_factory=Counts)
    gates: list[Gate] = field(default_factory=list)
    done_today: int = 0
    slots: list[Slot] = field(default_factory=list)
    spend: dict[str, int] = field(default_factory=dict)
    conductors: list[ConductorPing] = field(default_factory=list)
    tail: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Card:
    id: str
    project: str
    title: str
    importance: str
    status: str
    step: str | None
    loop: int
    loop_max: int
    provider: str
    parallel: bool
    added: int
    removed: int
    findings: int
    updated: datetime


@dataclass
class Column:
    key: str
    title: str
    cards: list[Card] = field(default_factory=list)


@dataclass
class Board:
    columns: list[Column] = field(default_factory=list)


def overview(paths: StorePaths | None = None, *, window: Window = "today") -> Overview:
    """The Overview screen: what runs, what waits, what needs the user, what it cost."""
    paths = paths or StorePaths.default()
    found = Overview(projects=_projects(paths), paused=runtime.pause_state(paths).everything)
    events = _events(paths)
    reasons = _reasons(events)
    for slug, doc in _tickets(paths, None):
        ticket = doc.meta
        if ticket.folder is Folder.in_queue:
            _queue(found.queue, ticket)
        elif ticket.folder is Folder.in_process and ticket.sub_status in GATES:
            found.gates.append(
                Gate(
                    ticket.id,
                    slug,
                    ticket.status,
                    ticket.title,
                    ticket.loop,
                    ticket.loop_max,
                    reasons.get(ticket.id, ""),
                )
            )
        elif ticket.folder is Folder.in_process and ticket.sub_status not in WAITING:
            provider, model = _agent(paths, slug, ticket)
            found.sessions.append(
                Session(
                    ticket.id,
                    slug,
                    ticket.title,
                    ticket.step or "",
                    ticket.status,
                    provider,
                    model,
                    ticket.loop,
                    ticket.loop_max,
                    ticket.updated,
                )
            )
    today = utc_now().date()
    found.done_today = sum(1 for event in events if _done(event) and event.ts.date() == today)
    found.spend = _spend(events, window)
    found.slots = _slots(paths)
    fresh = utc_now() - FRESH_PING
    found.conductors = [ping for ping in runtime.load_pings(paths) if ping.time >= fresh]
    found.tail = [event.model_dump(mode="json", exclude_none=True) for event in events[-TAIL:]]
    return found


def board(paths: StorePaths | None = None, *, project: str | None = None) -> Board:
    """The Task board: every ticket of the project (or of all) in its status column."""
    paths = paths or StorePaths.default()
    columns = {key: Column(key, title) for key, title in COLUMNS}
    diffs = _diffs(_events(paths))
    for slug, doc in _tickets(paths, project):
        ticket = doc.meta
        added, removed = diffs.get(ticket.id, (0, 0))
        provider, _ = _agent(paths, slug, ticket) if ticket.step else ("", "")
        findings = sum(
            line.startswith("- ") for line in doc.sections.get("Findings", "").splitlines()
        )
        card = Card(
            ticket.id,
            slug,
            ticket.title,
            ticket.importance.value,
            ticket.status,
            ticket.step,
            ticket.loop,
            ticket.loop_max,
            provider,
            bool(ticket.touches),
            added,
            removed,
            findings,
            ticket.updated,
        )
        columns[_column(ticket)].cards.append(card)
    for column in columns.values():
        column.cards.sort(key=lambda card: (card.updated, card.id), reverse=column.key == "done")
    return Board(list(columns.values()))


def version() -> str:
    return __version__


def journal_end() -> JournalCursor:
    """Where the journal ends now, for an event stream to start from."""
    return journal.end(StorePaths.default())


def events_after(cursor: JournalCursor) -> tuple[list[dict[str, Any]], JournalCursor]:
    """Journal events written after `cursor`, as JSON-ready mappings, and the new cursor."""
    events, cursor = journal.read_after(StorePaths.default(), cursor)
    return [event.model_dump(mode="json", exclude_none=True) for event in events], cursor


def _column(ticket: Ticket) -> str:
    if ticket.folder is Folder.in_queue:
        return "in_queue"
    if ticket.folder is Folder.done:
        return "done"
    if ticket.sub_status in GATES:
        return "needs_you"
    if ticket.sub_status in WAITING or ticket.step not in dict(COLUMNS):
        return "waiting"
    return str(ticket.step)


def _projects(paths: StorePaths) -> list[str]:
    return sorted(load_registry(paths).projects) if paths.registry.exists() else []


def _tickets(paths: StorePaths, project: str | None) -> list[tuple[str, Doc[Ticket]]]:
    slugs = records.scope(paths, project) if project else _projects(paths)
    return [
        (slug, doc)
        for slug in slugs
        for doc in sorted(records.project_tickets(paths, slug).values(), key=lambda d: d.meta.id)
    ]


def _events(paths: StorePaths) -> list[Event]:
    return list(journal.read(paths)) if paths.journal.is_dir() else []


def _reasons(events: list[Event]) -> dict[str, str]:
    """The reason of each ticket's latest status event."""
    reasons: dict[str, str] = {}
    for event in events:
        reason = (event.model_extra or {}).get("reason")
        if event.ticket and reason and event.type.startswith("ticket."):
            reasons[event.ticket] = str(reason)
    return reasons


def _done(event: Event) -> bool:
    to = str((event.model_extra or {}).get("to", ""))
    return event.type == "ticket.merged" or (
        event.type == "ticket.moved" and to.startswith("done/")
    )


def _spend(events: list[Event], window: Window) -> dict[str, int]:
    now = utc_now()
    since = {
        "today": datetime.combine(now.date(), datetime.min.time(), now.tzinfo),
        "7d": now - timedelta(days=7),
        "all": datetime.min.replace(tzinfo=now.tzinfo),
    }[window]
    spend: dict[str, int] = defaultdict(int)
    for event in events:
        extra = event.model_extra or {}
        if event.type == "step.end" and event.ts >= since and extra.get("provider"):
            tokens = extra.get("tokens") or {}
            spend[str(extra["provider"])] += int(tokens.get("in", 0)) + int(tokens.get("out", 0))
    return dict(spend)


def _diffs(events: list[Event]) -> dict[str, tuple[int, int]]:
    diffs: dict[str, tuple[int, int]] = {}
    for event in events:
        extra = event.model_extra or {}
        if event.type == "step.end" and event.ticket:
            added, removed = diffs.get(event.ticket, (0, 0))
            diffs[event.ticket] = (
                added + int(extra.get("added") or 0),
                removed + int(extra.get("removed") or 0),
            )
    return diffs


def _queue(counts: Counts, ticket: Ticket) -> None:
    sub = ticket.sub_status
    counts.ready += sub == "ready"
    counts.blocked += sub == "blocked"
    counts.parked += sub == "parked"
    if sub in ("ready", "blocked"):
        counts.parallel += bool(ticket.touches)
        counts.serial += not ticket.touches


def _agent(paths: StorePaths, slug: str, ticket: Ticket) -> tuple[str, str]:
    """The provider and model running (or next to run) the ticket's step."""
    running = runtime.load_ticket_state(paths, ticket.id).running
    if running is not None:
        return running.provider, running.model or "default"
    role = STEP_ROLES.get(ticket.step or "")
    if role is None:
        return ("user" if ticket.step == "approve" else ""), ""
    try:
        provider, model = split_cli(settings.load(paths, slug).agents[role].cli)
    except (HarnessError, KeyError):
        return "", ""
    return provider, model or "default"


def _slots(paths: StorePaths) -> list[Slot]:
    try:
        limits = settings.load(paths).sessions.per_provider
    except HarnessError:
        return []
    held: dict[str, int] = defaultdict(int)
    for entry in runtime.load_slots(paths).held:
        held[entry.provider] += 1
    return [Slot(provider, held[provider], total) for provider, total in limits.items()]
