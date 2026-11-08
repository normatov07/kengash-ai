"""Ticket lifecycle: add, show, list, find, set, move (SP2 spec §2.9, §2.16, §2.17, §3, §4)."""

import difflib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from kengash_ai import settings
from kengash_ai.model import (
    SUB_STATUSES,
    Doc,
    Event,
    Folder,
    NeedsUser,
    Part,
    Plan,
    PlanMode,
    PlanStatus,
    Settings,
    Ticket,
    TicketInput,
    UserError,
    utc_now,
)
from kengash_ai.ops import jobs, records, slots
from kengash_ai.ops.workspace import resolve_slug
from kengash_ai.store import documents
from kengash_ai.store.ids import new_id
from kengash_ai.store.locks import locked
from kengash_ai.store.paths import ProjectPaths, StorePaths
from kengash_ai.store.yamlio import load_yaml

SETTABLE = ("title", "importance", "workflow", "gate", "loop_max", "touches", "depends_on", "tags")
LISTS = frozenset({"touches", "depends_on", "tags"})
QUEUED = ("in_queue/ready", "in_queue/blocked")
MET = ("done/merged", "done/closed")  # dependents start from merged code (SP3 spec decision 6)


@dataclass
class NewTicket:
    id: str
    key: str | None
    title: str
    status: str


@dataclass
class Batch:
    plan: str
    project: str
    tickets: list[NewTicket]


@dataclass
class TicketLine:
    id: str
    project: str
    status: str
    importance: str
    title: str


@dataclass
class Moved:
    id: str
    project: str
    before: str
    after: str
    ready: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    stopped: bool = False  # the move out of in_process stopped the ticket's worker


@dataclass
class Updated:
    id: str
    project: str
    fields: dict[str, Any]
    status: str


def add_tickets(plan_id: str, text: str, *, project: str | None, by: str) -> Batch:
    """Validate a YAML or JSON ticket list for an approved plan, then queue every ticket."""
    items = _parse_batch(text)
    paths = StorePaths.default()
    slug, plan_path = records.locate_plan(paths, plan_id, project)
    resolved = settings.load(paths, slug)
    for number, item in enumerate(items, 1):
        flow = resolved.workflow_for(item.importance.value)
        if flow not in resolved.workflows:
            raise UserError(f"ticket {number}: settings have no workflow {flow!r}")
    project_paths = paths.project(slug)
    with locked(paths.locks / f"{slug}.lock"):
        plan_doc = records.load_plan(plan_path)
        plan = plan_doc.meta
        _check_plan(plan)
        existing = records.project_tickets(paths, slug)
        _check_references(items, existing)
        taken = records.taken_ids(paths)
        fresh: list[tuple[str, UUID]] = []
        for _ in items:
            fresh.append(new_id(taken))
            taken.add(fresh[-1][0])
        ids = {item.key: pair[0] for item, pair in zip(items, fresh, strict=True) if item.key}
        now = utc_now()
        made: list[NewTicket] = []
        for item, (ticket_id, uuid) in zip(items, fresh, strict=True):
            depends_on = list(dict.fromkeys(ids.get(ref, ref) for ref in item.depends_on))
            ticket = Ticket(
                id=ticket_id,
                uuid=uuid,
                project=slug,
                plan=plan.id,
                title=item.title,
                importance=item.importance,
                workflow=resolved.workflow_for(item.importance.value),
                status="in_queue/ready" if _met(depends_on, existing) else "in_queue/blocked",
                gate=item.gate,
                loop_max=getattr(resolved.loop_max, item.importance.value),
                depends_on=depends_on,
                touches=item.touches,
                tags=item.tags,
                created=now,
                updated=now,
            )
            acceptance = "\n".join(f"- [ ] {line}" for line in item.acceptance)
            sections = {"Scope": item.scope.strip(), "Acceptance": acceptance}
            documents.save_ticket(project_paths, Doc(ticket, sections))
            made.append(NewTicket(ticket.id, item.key, ticket.title, ticket.status))
        plan.tickets = [*plan.tickets, *(new.id for new in made)]
        plan.status = PlanStatus.ticketed
        plan.updated = now
        documents.save_plan(project_paths, plan_doc)
    created = [
        Event(
            type="ticket.created",
            project=slug,
            ticket=new.id,
            plan=plan.id,
            title=new.title,
            status=new.status,
            by=by,
        )
        for new in made
    ]
    records.record(paths, f"kengash: ticket add {' '.join(new.id for new in made)}", *created)
    return Batch(plan.id, slug, made)


MAX_PARTS = 6


def split_problem(
    ticket: Ticket, sections: Mapping[str, str], parts: Sequence[Part], resolved: Settings
) -> str:
    """Why a plan's `parts` may not replace the ticket; "" when they may (SP17 spec §3.6). A
    split that loses an acceptance line is refused, so a model cannot drop scope by splitting."""
    limit = resolved.plan.max_files
    if limit == 0:
        return "splitting is off (plan.max_files: 0)"
    if ticket.loop != 1:
        return "a ticket splits only on its first loop"
    if not 2 <= len(parts) <= MAX_PARTS:
        return f"a split needs at least 2 parts and at most {MAX_PARTS}"
    for index, part in enumerate(parts):
        if not part.files:
            return f"part {index + 1} names no files"
        if any(not 0 <= earlier < index for earlier in part.after):
            return f"part {index + 1}: `after` must name earlier parts"
    if len({name for part in parts for name in part.files}) <= limit:
        return f"the parts name at most {limit} files: no split needed"
    covered = {_line(line) for part in parts for line in part.acceptance}
    for line in sections.get("Acceptance", "").splitlines():
        if line.strip() and _line(line) not in covered:
            return f"no part keeps the acceptance line: {line.strip()[:80]}"
    return ""


def split(
    paths: StorePaths, slug: str, doc: Doc[Ticket], parts: Sequence[Part], *, by: str
) -> list[Event]:
    """Narrow the ticket to `parts[0]` and queue the rest (the caller holds the project lock
    and saves `doc`); returns the `ticket.created` events. A part waits for its `after` parts,
    else for what the ticket itself waited for, and dependents wait for every part."""
    ticket = doc.meta
    project = paths.project(slug)
    existing = records.project_tickets(paths, slug) | {ticket.id: doc}
    taken = records.taken_ids(paths)
    ids = [ticket.id]
    fresh: list[UUID] = []
    for _ in parts[1:]:
        new, uuid = new_id(taken)
        taken.add(new)
        ids.append(new)
        fresh.append(uuid)
    now = utc_now()
    created: list[Event] = []
    for index, part in enumerate(parts[1:], 1):
        needs = [ids[earlier] for earlier in part.after] or list(ticket.depends_on)
        made = ticket.model_copy(
            update={
                "id": ids[index],
                "uuid": fresh[index - 1],
                "title": part.title,
                "status": "in_queue/ready" if _met(needs, existing) else "in_queue/blocked",
                "step": None,
                "loop": 1,
                "tokens": 0,
                "tokens_max": None,
                "depends_on": needs,
                "touches": list(part.files),
                "branch": None,
                "sessions": {},
                "created": now,
                "updated": now,
            }
        )
        documents.save_ticket(project, Doc(made, _part_sections(part)))
        created.append(
            Event(
                type="ticket.created",
                project=slug,
                ticket=made.id,
                plan=made.plan,
                title=made.title,
                status=made.status,
                by=by,
            )
        )
    first = parts[0]
    ticket.title = first.title
    ticket.touches = list(first.files)
    doc.sections.update(_part_sections(first))
    for other in existing.values():
        if ticket.id in other.meta.depends_on and other.meta.id != ticket.id:
            other.meta.depends_on = list(dict.fromkeys([*other.meta.depends_on, *ids[1:]]))
            documents.save_ticket(project, other)
    _add_to_plan(paths, slug, ticket.plan, ids[1:])
    return created


def _part_sections(part: Part) -> dict[str, str]:
    return {
        "Scope": part.scope.strip(),
        "Acceptance": "\n".join(f"- [ ] {_plain(line)}" for line in part.acceptance),
    }


def _plain(text: str) -> str:
    """An acceptance line without its checkbox."""
    return text.strip().removeprefix("- [ ]").removeprefix("- [x]").strip()


def _line(text: str) -> str:
    """An acceptance line for comparing: its checkbox gone, spaces and case folded."""
    return " ".join(_plain(text).split()).casefold()


def _add_to_plan(paths: StorePaths, slug: str, plan_id: str, ids: Sequence[str]) -> None:
    try:
        _, path = records.locate_plan(paths, plan_id, slug)
    except UserError:  # a missing plan only costs its ticket list
        return
    plan_doc = records.load_plan(path)
    plan_doc.meta.tickets = [*plan_doc.meta.tickets, *ids]
    documents.save_plan(paths.project(slug), plan_doc)


def show_ticket(ticket_id: str, *, project: str | None) -> records.Document:
    """The ticket file, its frontmatter and its sections."""
    paths = StorePaths.default()
    slug, path = records.locate_ticket(paths, ticket_id, project)
    return records.document(slug, path, records.load_ticket(path))


def list_tickets(
    *, project: str | None, cwd: Path, folder: Folder | None = None
) -> list[TicketLine]:
    """Tickets of the named project, else of the project here, else of every project."""
    paths = StorePaths.default()
    return _lines(
        (slug, doc.meta)
        for slug in _scope_here(paths, project, cwd)
        for doc in records.project_tickets(paths, slug).values()
        if folder is None or doc.meta.folder is folder
    )


def find_tickets(text: str, *, project: str | None, cwd: Path) -> list[TicketLine]:
    """Tickets whose title, tags or sections contain `text`, ignoring case."""
    needle = text.strip().casefold()
    if not needle:
        raise UserError("nothing to find")
    paths = StorePaths.default()
    return _lines(
        (slug, doc.meta)
        for slug in _scope_here(paths, project, cwd)
        for doc in records.project_tickets(paths, slug).values()
        if needle in " ".join([doc.meta.title, *doc.meta.tags, *doc.sections.values()]).casefold()
    )


def move_ticket(ticket_id: str, target: str, why: str, *, project: str | None, by: str) -> Moved:
    """Move a ticket to FOLDER[/SUB]; queued tickets then turn ready or blocked to match.
    A move out of in_process stops the ticket's worker first and frees its slots."""
    reason = records.one_line(why, "why")
    paths = StorePaths.default()
    slug, path = records.locate_ticket(paths, ticket_id, project)
    steps = tuple(settings.load(paths, slug).status.names.values())
    project_paths = paths.project(slug)
    with locked(paths.locks / f"{slug}.lock"):
        doc = records.load_ticket(path)
        tickets = records.project_tickets(paths, slug) | {doc.meta.id: doc}
        ticket = doc.meta
        before, after = ticket.status, _target(target, ticket, tickets, steps)
        if after == before:
            return Moved(ticket.id, slug, before, after)
        stopped = False
        if ticket.folder is Folder.in_process and not after.startswith("in_process/"):
            stopped = jobs.end(paths, ticket.id)
            slots.release(paths, ticket.id)
        ticket.status = after
        if ticket.folder is Folder.done:
            ticket.step = None  # a done ticket runs no step; parked or requeued ones resume
        ticket.updated = utc_now()
        documents.save_ticket(project_paths, doc)
        ready, blocked = refresh_queue(project_paths, tickets)
    note = f"{ticket.id} moved to {after}"
    events = [_moved(slug, ticket.id, before, after, reason, by)]
    events += [_moved(slug, tid, QUEUED[1], QUEUED[0], note, "kengash") for tid in ready]
    events += [_moved(slug, tid, QUEUED[0], QUEUED[1], note, "kengash") for tid in blocked]
    records.record(paths, f"kengash: ticket move {ticket.id}", *events)
    return Moved(ticket.id, slug, before, after, ready, blocked, stopped)


def set_fields(ticket_id: str, pairs: Sequence[str], *, project: str | None, by: str) -> Updated:
    """Change frontmatter fields from KEY=VALUE pairs; lists take `[a, b]` or `a,b`."""
    changes = _parse_pairs(pairs)
    paths = StorePaths.default()
    slug, path = records.locate_ticket(paths, ticket_id, project)
    workflows = settings.load(paths, slug).workflows
    project_paths = paths.project(slug)
    with locked(paths.locks / f"{slug}.lock"):
        doc = records.load_ticket(path)
        tickets = records.project_tickets(paths, slug) | {doc.meta.id: doc}
        ticket = doc.meta
        try:
            for key, value in changes.items():
                setattr(ticket, key, value)
        except ValidationError as exc:
            raise UserError(records.describe(exc)) from exc
        if "workflow" in changes and ticket.workflow not in workflows:
            raise UserError(f"settings have no workflow {ticket.workflow!r}")
        if ticket.loop_max < ticket.loop:
            raise UserError(f"loop_max cannot go below the current loop ({ticket.loop})")
        if "depends_on" in changes:
            unknown = [dep for dep in ticket.depends_on if dep not in tickets]
            if unknown:
                raise UserError(f"unknown dependency {', '.join(unknown)}")
            cycle = _cycle({tid: item.meta.depends_on for tid, item in tickets.items()})
            if cycle:
                raise UserError(f"dependency cycle: {' -> '.join(cycle)}")
        ticket.updated = utc_now()
        documents.save_ticket(project_paths, doc)
        refresh_queue(project_paths, tickets)
    values = ticket.model_dump(mode="json")
    fields = {key: values[key] for key in changes}
    updated = Event(
        type="ticket.updated",
        project=slug,
        ticket=ticket.id,
        fields=fields,
        status=ticket.status,
        by=by,
    )
    records.record(paths, f"kengash: ticket set {ticket.id}", updated)
    return Updated(ticket.id, slug, fields, ticket.status)


def _parse_batch(text: str) -> list[TicketInput]:
    data = load_yaml(text, "ticket list")
    if not isinstance(data, list) or not data:
        raise UserError("ticket list: expected a non-empty YAML or JSON list")
    items: list[TicketInput] = []
    for number, raw in enumerate(data, 1):
        try:
            items.append(TicketInput.model_validate(raw))
        except ValidationError as exc:
            prefix = f"ticket {number}: "
            raise UserError(records.describe(exc, prefix, TicketInput.model_fields)) from exc
    return items


def _check_plan(plan: Plan) -> None:
    if plan.status in (PlanStatus.approved, PlanStatus.ticketed):
        return
    if plan.mode is PlanMode.quick and plan.status is PlanStatus.draft:
        return  # the user's check of the ticket list approves a quick plan
    if plan.status is PlanStatus.rejected:
        raise UserError(f"plan {plan.id} was rejected")
    raise NeedsUser(
        f"plan {plan.id} is {plan.status.value}; the user approves it first: "
        f"kengash plan approve {plan.id}"
    )


def _check_references(items: Sequence[TicketInput], existing: Mapping[str, Doc[Ticket]]) -> None:
    """Keys are unique, every dependency is a key or an existing ticket, and nothing loops."""
    keys = [item.key for item in items if item.key]
    repeated = sorted({key for key in keys if keys.count(key) > 1})
    if repeated:
        raise UserError(f"keys used twice: {', '.join(repeated)}")
    clashes = sorted(set(keys) & set(existing))
    if clashes:
        raise UserError(f"keys equal to existing ticket ids: {', '.join(clashes)}")
    for number, item in enumerate(items, 1):
        unknown = [ref for ref in item.depends_on if ref not in keys and ref not in existing]
        if unknown:
            raise UserError(f"ticket {number}: unknown dependency {', '.join(unknown)}")
    cycle = _cycle({item.key: item.depends_on for item in items if item.key})
    if cycle:
        raise UserError(f"dependency cycle: {' -> '.join(cycle)}")


def _cycle(graph: Mapping[str, Sequence[str]]) -> list[str] | None:
    """A dependency loop as a path that ends where it starts, or None."""
    finished: set[str] = set()
    path: list[str] = []

    def visit(node: str) -> list[str] | None:
        if node in path:
            return [*path[path.index(node) :], node]
        if node in finished or node not in graph:
            return None
        path.append(node)
        for target in graph[node]:
            found = visit(target)
            if found:
                return found
        path.pop()
        finished.add(node)
        return None

    for node in graph:
        found = visit(node)
        if found:
            return found
    return None


def _met(depends_on: Iterable[str], tickets: Mapping[str, Doc[Ticket]]) -> bool:
    """True when every dependency is a ticket of this project that is merged or closed."""
    return all(dep in tickets and tickets[dep].meta.status in MET for dep in depends_on)


def _target(
    target: str, ticket: Ticket, tickets: Mapping[str, Doc[Ticket]], steps: Sequence[str]
) -> str:
    """The full status a move to `target` means, once it is allowed."""
    name, _, sub = target.partition("/")
    try:
        folder = Folder(name)
    except ValueError:
        raise UserError(f"unknown folder {name!r}; use in_queue, in_process or done") from None
    met = _met(ticket.depends_on, tickets)
    if folder is Folder.in_queue and sub in ("", "ready", "blocked"):
        sub = "ready" if met else "blocked"
    elif folder is Folder.done and not sub:
        sub = "closed"
    allowed = sorted({*SUB_STATUSES[folder], *(steps if folder is Folder.in_process else ())})
    if sub not in allowed:
        problem = f"has no {sub!r}" if sub else "needs a sub-status"
        raise UserError(f"{folder.value} {problem}; use one of: {', '.join(allowed)}")
    if folder is Folder.in_process and not met:
        waiting = [dep for dep in ticket.depends_on if not _met([dep], tickets)]
        raise UserError(f"{ticket.id} waits on {', '.join(waiting)}")
    return f"{folder.value}/{sub}"


def refresh_queue(
    project: ProjectPaths, tickets: Mapping[str, Doc[Ticket]]
) -> tuple[list[str], list[str]]:
    """Turn each ready or blocked ticket ready or blocked to match its dependencies."""
    ready: list[str] = []
    blocked: list[str] = []
    for doc in tickets.values():
        ticket = doc.meta
        if ticket.status not in QUEUED:
            continue
        wanted = QUEUED[0] if _met(ticket.depends_on, tickets) else QUEUED[1]
        if wanted != ticket.status:
            ticket.status = wanted
            ticket.updated = utc_now()
            documents.save_ticket(project, doc)
            (ready if wanted == QUEUED[0] else blocked).append(ticket.id)
    return sorted(ready), sorted(blocked)


def _moved(slug: str, ticket_id: str, before: str, after: str, why: str, by: str) -> Event:
    return Event.model_validate(
        {
            "type": "ticket.moved",
            "project": slug,
            "ticket": ticket_id,
            "from": before,
            "to": after,
            "why": why,
            "by": by,
        }
    )


def _parse_pairs(pairs: Sequence[str]) -> dict[str, Any]:
    if not pairs:
        raise UserError("nothing to set; pass KEY=VALUE pairs")
    changes: dict[str, Any] = {}
    for pair in pairs:
        key, sep, raw = pair.partition("=")
        key = key.strip()
        if not sep:
            raise UserError(f"{pair!r} is not KEY=VALUE")
        if key == "status":
            raise UserError("status changes through: kengash ticket move ID FOLDER[/SUB] --why W")
        if key not in SETTABLE:
            hint = difflib.get_close_matches(key, SETTABLE, n=1)
            help_text = f"did you mean {hint[0]}?" if hint else f"settable: {', '.join(SETTABLE)}"
            raise UserError(f"cannot set {key!r}; {help_text}")
        changes[key] = _list(raw) if key in LISTS else raw.strip()
    return changes


def _list(raw: str) -> list[Any]:
    text = raw.strip()
    if text.startswith("["):
        value = load_yaml(text, "list")
        if not isinstance(value, list):
            raise UserError(f"{text!r} is not a list")
        return value
    return [part.strip() for part in text.split(",") if part.strip()]


def _scope_here(paths: StorePaths, project: str | None, cwd: Path) -> list[str]:
    slug = resolve_slug(project, cwd, paths)
    return [slug] if slug is not None else records.scope(paths, None)


def _lines(found: Iterable[tuple[str, Ticket]]) -> list[TicketLine]:
    order = list(Folder)
    ranked = sorted(
        found,
        key=lambda pair: (pair[0], order.index(pair[1].folder), pair[1].created, pair[1].id),
    )
    return [
        TicketLine(ticket.id, slug, ticket.status, ticket.importance.value, ticket.title)
        for slug, ticket in ranked
    ]
