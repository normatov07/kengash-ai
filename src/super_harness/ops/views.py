"""Read models for the UI screens (SP5 spec §3): plain dataclasses built from the store,
the runtime files and the journal. Nothing here writes."""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from super_harness import __version__, journal, settings, workflow
from super_harness.model import (
    PROVIDERS,
    STEP_ROLES,
    ConductorPing,
    Doc,
    Event,
    Folder,
    HarnessError,
    JournalCursor,
    ProviderStatus,
    Ticket,
    Workflow,
    split_cli,
    utc_now,
)
from super_harness.model import Gate as TicketGate
from super_harness.ops import agents, records
from super_harness.ops import changes as changes_ops
from super_harness.ops import projects as project_ops
from super_harness.ops import skills as skill_ops
from super_harness.ops.workspace import GATES
from super_harness.store import links as store_links
from super_harness.store import runtime
from super_harness.store.paths import StorePaths
from super_harness.store.registry import load_registry

Window = Literal["today", "7d", "all"]
WAITING = ("waiting_slot", "waiting_quota", "paused")
TAIL = 30
NEARBY_DEPTH = 2  # levels below each registered repo's parent folder
FRESH_PING = timedelta(minutes=10)
_parsed: dict[Path, tuple[tuple[int, int], list[Event]]] = {}  # day file → (stat, events)
DETECT_S = 60.0
_detected: dict[str, tuple[float, ProviderStatus]] = {}  # provider → (when, status)
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
    links_broken: int = 0  # projects whose folder or memory link needs a fix
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


@dataclass
class ProjectLink:
    """One project's view of the store (system spec §4.2): its repo's folder link, the
    project's memory link and the exclude entry, and the one action that fixes them."""

    project: str
    repo: str
    link: str
    target: str
    state: str
    memory: str
    excluded: bool | None
    tickets: int
    fix: Literal["", "repair", "relink", "adopt", "manual"]
    hint: str


@dataclass
class FoundStore:
    """A real `.harness/` folder beside a registered repo that the store does not know."""

    path: str
    repo: str
    tickets: int
    plans: int


@dataclass
class Links:
    projects: list[ProjectLink] = field(default_factory=list)
    nearby: list[FoundStore] = field(default_factory=list)
    intact: int = 0
    total: int = 0


@dataclass
class SettingsView:
    """One scope's settings (SP5 spec decision 8): resolved values, the keys this scope
    overrides, and its SETTINGS.md as written."""

    scope: str | None
    projects: list[str]
    values: dict[str, Any]
    set_here: list[str]
    file: str
    path: str
    repo_path: str | None
    problem: str = ""


@dataclass
class ProviderCard:
    name: str
    installed: bool
    signed_in: bool
    supported: bool
    version: str | None
    hint: str
    slots_used: int
    slots_total: int
    spend: int


@dataclass
class Role:
    role: str
    on: bool
    cli: str
    provider: str
    model: str
    skill: str
    skill_file: str
    blocking: bool
    fallback: list[str]
    used_in: list[str]
    tokens: int


@dataclass
class AgentsView:
    """The Agents screen for one scope: providers, the role roster, limits and routing."""

    scope: str | None
    projects: list[str]
    providers: list[ProviderCard] = field(default_factory=list)
    roster: list[Role] = field(default_factory=list)
    sessions_max: int = 0
    tokens_per_ticket: int = 0
    fallback_on_rate_limit: bool = True
    per_provider: dict[str, int] = field(default_factory=dict)
    routing: dict[str, list[str]] = field(default_factory=dict)
    set_here: list[str] = field(default_factory=list)
    problem: str = ""


@dataclass
class WorkflowsView:
    """The Workflow editor for one scope (SP5 spec decision 10): each workflow as written,
    the steps a ticket would run, loop caps per importance and each role's CLI."""

    scope: str | None
    projects: list[str]
    names: list[str] = field(default_factory=list)
    workflows: dict[str, Workflow] = field(default_factory=dict)
    effective: dict[str, list[str]] = field(default_factory=dict)
    warnings: dict[str, str] = field(default_factory=dict)
    loop_max: dict[str, int] = field(default_factory=dict)
    loop_ask_at_cap: bool = True
    agents: dict[str, str] = field(default_factory=dict)
    skills: dict[str, str] = field(default_factory=dict)
    off: list[str] = field(default_factory=list)  # roles switched off: their steps are skipped
    plan_review: bool = True  # False at plan.review_max 0: review_plan is skipped
    library: list[str] = field(default_factory=lambda: list(STEP_ROLES))
    roles: dict[str, str | None] = field(default_factory=lambda: dict(STEP_ROLES))
    set_here: list[str] = field(default_factory=list)
    problem: str = ""


@dataclass
class TicketLink:
    id: str
    title: str
    status: str


@dataclass
class PlanRef:
    id: str
    title: str
    prompt: str
    found: bool


@dataclass
class TimelineStep:
    """One row of a ticket's timeline: a step that ended, or a status change."""

    ts: datetime
    kind: str
    step: str = ""
    role: str = ""
    provider: str = ""
    model: str = ""
    verdict: str = ""
    loop: int | None = None
    tokens: int = 0
    duration_s: float | None = None
    note: str = ""


@dataclass
class ChainStep:
    step: str
    role: str | None
    runs: int
    state: Literal["done", "running", "waiting", "needs you", "pending"]


@dataclass
class TicketView:
    """Ticket detail: the file, its plan and neighbours, what it changed, and its history."""

    project: str
    meta: dict[str, Any]
    sections: dict[str, str]
    file: str
    store_path: str
    repo_path: str
    plan: PlanRef
    siblings: list[TicketLink] = field(default_factory=list)
    depends_on: list[TicketLink] = field(default_factory=list)
    blocks: list[TicketLink] = field(default_factory=list)
    changes: list[changes_ops.Change] = field(default_factory=list)
    timeline: list[TimelineStep] = field(default_factory=list)
    memory_writes: list[dict[str, Any]] = field(default_factory=list)
    chain: list[ChainStep] = field(default_factory=list)
    attach: str = ""
    grant: int = 2  # loops one approval adds (`loop_grant`)


def overview(paths: StorePaths | None = None, *, window: Window = "today") -> Overview:
    """The Overview screen: what runs, what waits, what needs the user, what it cost."""
    paths = paths or StorePaths.default()
    found = Overview(projects=_projects(paths), paused=runtime.pause_state(paths).everything)
    found.links_broken = sum(1 for link in links(paths, nearby=False).projects if link.fix)
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


def links(paths: StorePaths | None = None, *, nearby: bool = True) -> Links:
    """Link health for the Memory screen: every project's links and, with `nearby`, the real
    `.harness/` folders beside registered repos."""
    paths = paths or StorePaths.default()
    found = Links()
    if not paths.registry.exists():
        return found
    entries = load_registry(paths).projects
    for slug, entry in sorted(entries.items()):
        found.projects.append(_project_link(paths, slug, entry.path))
    found.total = len(found.projects)
    found.intact = sum(1 for link in found.projects if not link.fix)
    if not nearby:
        return found
    known = {entry.path.resolve() for entry in entries.values()}
    roots = {entry.path.resolve().parent for entry in entries.values()}
    seen: set[Path] = set()
    for root in sorted(roots):
        for folder in project_ops.real_folders(root, NEARBY_DEPTH):
            if folder.parent.resolve() in known or folder in seen:
                continue
            seen.add(folder)
            tickets = len(list(folder.glob("tasks/*/*.md")))
            found.nearby.append(
                FoundStore(
                    str(folder), str(folder.parent), tickets, len(list(folder.glob("plans/*.md")))
                )
            )
    return found


def _project_link(paths: StorePaths, slug: str, repo: Path) -> ProjectLink:
    project = paths.project(slug)
    tickets = len(list(project.root.glob("tasks/*/*.md")))
    memory = store_links.state_of(project.memory_link, paths.memory).value
    link = str(repo / store_links.LINK)
    if not repo.is_dir():
        hint = f"harness link {slug} <new-path>"
        return ProjectLink(
            slug,
            str(repo),
            link,
            str(project.root),
            "repo missing",
            memory,
            None,
            tickets,
            "relink",
            hint,
        )
    state = store_links.link_state(repo, project.root)
    excluded = store_links.is_excluded(repo)
    fix: Literal["", "repair", "relink", "adopt", "manual"] = ""
    hint = ""
    if state is store_links.LinkState.real_dir:
        fix, hint = "adopt", f"harness adopt {repo}"
    elif state is store_links.LinkState.blocked or memory in ("real folder", "blocked by a file"):
        fix, hint = "manual", "harness doctor"
    elif state is not store_links.LinkState.ok or memory != "ok" or excluded is False:
        fix, hint = "repair", "harness doctor --fix"
    return ProjectLink(
        slug, str(repo), link, str(project.root), state.value, memory, excluded, tickets, fix, hint
    )


def settings_view(paths: StorePaths | None = None, *, project: str | None) -> SettingsView:
    """The Settings screen for the defaults (`project=None`) or one project."""
    paths = paths or StorePaths.default()
    if project is None:
        path, repo_path = paths.defaults / "SETTINGS.md", None
    else:
        repo = load_registry(paths).projects[records.scope(paths, project)[0]].path
        path, repo_path = (
            paths.project(project).settings,
            str(repo / store_links.LINK / "SETTINGS.md"),
        )
    found = SettingsView(
        project,
        _projects(paths),
        {},
        [],
        path.read_text(encoding="utf-8") if path.is_file() else "",
        str(path),
        repo_path,
    )
    try:
        found.values = settings.load(paths, project).model_dump(mode="json")
        found.set_here = settings.overrides(paths, project)
    except HarnessError as exc:
        found.problem = str(exc)
    return found


def agents_view(
    paths: StorePaths | None = None,
    *,
    project: str | None,
    window: Window = "today",
    refresh: bool = False,
) -> AgentsView:
    """The Agents screen; provider detection runs each CLI's sign-in check, so it is kept
    for DETECT_S unless `refresh`."""
    paths = paths or StorePaths.default()
    if project is not None:
        records.scope(paths, project)
    found = AgentsView(project, _projects(paths))
    try:
        resolved = settings.load(paths, project)
        found.set_here = settings.overrides(paths, project)
    except HarnessError as exc:
        found.problem = str(exc)
        return found
    events = _events(paths)
    spend = _spend(events, window)
    held: dict[str, int] = defaultdict(int)
    for entry in runtime.load_slots(paths).held:
        held[entry.provider] += 1
    for name, status in _statuses(paths, refresh).items():
        found.providers.append(
            ProviderCard(
                name,
                status.installed,
                status.signed_in,
                name not in agents.UNSUPPORTED,
                status.version,
                status.hint,
                held[name],
                resolved.sessions.per_provider.get(name, 0),
                spend.get(name, 0),
            )
        )
    tokens = _role_tokens(events, window)
    for role, agent in resolved.agents.items():
        provider, model = split_cli(agent.cli)
        used_in = [
            name
            for name, flow in resolved.workflows.items()
            if any(STEP_ROLES.get(step) == role for step in flow.steps)
        ]
        skill_file = skill_ops.role_file(paths, project, agent.skill)
        found.roster.append(
            Role(
                role,
                agent.on,
                agent.cli,
                provider,
                model or "default",
                agent.skill,
                str(skill_file) if skill_file else "",
                agent.blocking,
                agent.fallback,
                used_in,
                tokens.get(role, 0),
            )
        )
    found.sessions_max = resolved.sessions.max
    found.tokens_per_ticket = resolved.tokens.per_ticket_max
    found.fallback_on_rate_limit = resolved.fallback_on_rate_limit
    found.per_provider = dict(resolved.sessions.per_provider)
    found.routing = {name: list(flow.steps) for name, flow in resolved.workflows.items()}
    return found


def workflows_view(paths: StorePaths | None = None, *, project: str | None) -> WorkflowsView:
    """The Workflow editor's data for the defaults or one project."""
    paths = paths or StorePaths.default()
    if project is not None:
        records.scope(paths, project)
    found = WorkflowsView(project, _projects(paths))
    try:
        resolved = settings.load(paths, project)
        found.set_here = settings.overrides(paths, project)
    except HarnessError as exc:
        found.problem = str(exc)
        return found
    found.names = list(resolved.workflows)
    found.workflows = dict(resolved.workflows)
    for name in found.names:
        found.effective[name] = workflow.steps_for(resolved, name, hitl=False)
        off = workflow.blocking_off(resolved, name)
        if off:
            found.warnings[name] = f"{off} is blocking but switched off; tickets will stop there"
    found.loop_max = resolved.loop_max.model_dump()
    found.loop_ask_at_cap = resolved.loop_ask_at_cap
    found.agents = {role: agent.cli for role, agent in resolved.agents.items()}
    found.skills = {role: agent.skill for role, agent in resolved.agents.items()}
    found.off = [role for role, agent in resolved.agents.items() if not agent.on]
    found.plan_review = resolved.plan.review_max > 0
    return found


def ticket_view(
    paths: StorePaths | None = None, ticket_id: str = "", *, project: str | None
) -> TicketView:
    """Ticket detail; anything the ticket has not produced yet comes back empty."""
    paths = paths or StorePaths.default()
    slug, path = records.locate_ticket(paths, ticket_id, project)
    doc = records.load_ticket(path)
    ticket = doc.meta
    root = paths.project(slug).root
    repo = load_registry(paths).projects[slug].path
    found = TicketView(
        slug,
        ticket.model_dump(mode="json"),
        doc.sections,
        path.read_text(encoding="utf-8"),
        str(path),
        str(repo / store_links.LINK / path.relative_to(root)),
        _plan_ref(paths, slug, ticket.plan),
    )
    others = records.project_tickets(paths, slug)
    found.siblings = [
        _link(o.meta)
        for o in others.values()
        if o.meta.plan == ticket.plan and o.meta.id != ticket.id
    ]
    found.depends_on = [
        _link(others[dep].meta) if dep in others else TicketLink(dep, "(not found)", "")
        for dep in ticket.depends_on
    ]
    found.blocks = [_link(o.meta) for o in others.values() if ticket.id in o.meta.depends_on]
    try:
        found.changes = changes_ops.ticket_changes(ticket.id, diff=False, project=slug).changes
    except (HarnessError, OSError):
        found.changes = []
    try:
        found.attach = changes_ops.attach_command(ticket.id, role=None, project=slug).command
    except (HarnessError, OSError):
        found.attach = ""
    events = [event for event in _events(paths) if _about(event, ticket.id)]
    found.timeline = [row for event in events if (row := _timeline_row(event, ticket.id))]
    found.memory_writes = [
        event.model_dump(mode="json", exclude_none=True)
        for event in events
        if event.type == "memory.write"
    ]
    found.chain = _chain(paths, slug, ticket, found.timeline)
    found.grant = _grant(paths, slug)
    return found


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
    """Every journal event; a day file is parsed again only once it has grown."""
    if not paths.journal.is_dir():
        return []
    days = journal.days(paths)
    for stale in [path for path in _parsed if path.parent == paths.journal]:
        if stale not in days:
            del _parsed[stale]
    events: list[Event] = []
    for path in days:
        stat = path.stat()
        key = (stat.st_size, stat.st_mtime_ns)
        cached = _parsed.get(path)
        if cached is None or cached[0] != key:
            cached = _parsed[path] = (key, journal.read_day(path))
        events += cached[1]
    return events


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


def _since(window: Window) -> datetime:
    now = utc_now()
    return {
        "today": datetime.combine(now.date(), datetime.min.time(), now.tzinfo),
        "7d": now - timedelta(days=7),
        "all": datetime.min.replace(tzinfo=now.tzinfo),
    }[window]


def _spend(events: list[Event], window: Window) -> dict[str, int]:
    since = _since(window)
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


def _statuses(paths: StorePaths, refresh: bool) -> dict[str, ProviderStatus]:
    detect = agents.detector(paths)
    now = time.monotonic()
    found: dict[str, ProviderStatus] = {}
    for name in PROVIDERS:
        cached = _detected.get(name)
        if refresh or cached is None or now - cached[0] > DETECT_S:
            cached = _detected[name] = (now, detect(name))
        found[name] = cached[1]
    return found


def _role_tokens(events: list[Event], window: Window) -> dict[str, int]:
    since = _since(window)
    tokens: dict[str, int] = defaultdict(int)
    for event in events:
        extra = event.model_extra or {}
        if event.type == "step.end" and event.ts >= since and extra.get("role"):
            used = extra.get("tokens") or {}
            tokens[str(extra["role"])] += int(used.get("in", 0)) + int(used.get("out", 0))
    return dict(tokens)


STATUS_EVENTS = frozenset(
    {
        "ticket.needs_approval",
        "ticket.approved",
        "ticket.stalled",
        "ticket.failed",
        "ticket.awaiting_merge",
        "ticket.merged",
        "ticket.moved",
        "ticket.recirculated",
        "ticket.paused",
        "ticket.stopped",
    }
)


def _about(event: Event, ticket_id: str) -> bool:
    """The event concerns the ticket: it names it, or a memory write cites it."""
    if event.ticket == ticket_id:
        return True
    extra = event.model_extra or {}
    return event.type == "memory.write" and any(
        ticket_id in str(extra.get(key, "")) for key in ("why", "line")
    )


def _timeline_row(event: Event, ticket_id: str) -> TimelineStep | None:
    extra = event.model_extra or {}
    if event.ticket != ticket_id:
        return None
    if event.type == "step.end":
        used = extra.get("tokens") or {}
        return TimelineStep(
            event.ts,
            event.type,
            str(extra.get("step", "")),
            str(extra.get("role", "")),
            str(extra.get("provider", "")),
            str(extra.get("model", "")),
            str(extra.get("verdict", "")),
            extra.get("loop"),
            int(used.get("in", 0)) + int(used.get("out", 0)),
            extra.get("duration_s"),
        )
    if event.type in STATUS_EVENTS:
        note = extra.get("reason") or extra.get("why") or extra.get("to") or ""
        return TimelineStep(event.ts, event.type, note=str(note))
    return None


def _grant(paths: StorePaths, slug: str) -> int:
    try:
        return settings.load(paths, slug).loop_grant
    except HarnessError:
        return 2


def _chain(
    paths: StorePaths, slug: str, ticket: Ticket, rows: list[TimelineStep]
) -> list[ChainStep]:
    """The workflow's steps for this ticket and how far it got through them."""
    try:
        resolved = settings.load(paths, slug)
        steps = workflow.steps_for(resolved, ticket.workflow, hitl=ticket.gate is TicketGate.hitl)
    except (HarnessError, KeyError):
        return []
    current = steps.index(ticket.step) if ticket.step in steps else -1
    here: Literal["running", "waiting", "needs you"] = "running"
    if ticket.sub_status in GATES:
        here = "needs you"
    elif ticket.folder is not Folder.in_process or ticket.sub_status in WAITING:
        here = "waiting"
    chain = []
    for index, step in enumerate(steps):
        runs = sum(1 for row in rows if row.kind == "step.end" and row.step == step)
        state: Literal["done", "running", "waiting", "needs you", "pending"] = "pending"
        if ticket.folder is Folder.done or (current >= 0 and index < current):
            state = "done"
        elif index == current:
            state = here
        chain.append(ChainStep(step, STEP_ROLES.get(step), runs, state))
    return chain


def _link(ticket: Ticket) -> TicketLink:
    return TicketLink(ticket.id, ticket.title, ticket.status)


def _plan_ref(paths: StorePaths, slug: str, plan_id: str) -> PlanRef:
    try:
        _, path = records.locate_plan(paths, plan_id, slug)
        plan = records.load_plan(path)
    except HarnessError:
        return PlanRef(plan_id, "", "", False)
    return PlanRef(plan_id, plan.meta.title, plan.sections.get("Prompt", ""), True)


def _slots(paths: StorePaths) -> list[Slot]:
    try:
        limits = settings.load(paths).sessions.per_provider
    except HarnessError:
        return []
    held: dict[str, int] = defaultdict(int)
    for entry in runtime.load_slots(paths).held:
        held[entry.provider] += 1
    return [Slot(provider, held[provider], total) for provider, total in limits.items()]
