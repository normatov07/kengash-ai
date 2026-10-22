"""Ticket lifecycle: add, show, list, find, set, move (SP2 spec §2.9, §2.16, §2.17, §3, §4)."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from super_harness import settings
from super_harness.model import (
    Doc,
    Event,
    Folder,
    NeedsUser,
    Plan,
    PlanMode,
    PlanStatus,
    Ticket,
    TicketInput,
    UserError,
    utc_now,
)
from super_harness.ops import records
from super_harness.ops.workspace import resolve_slug
from super_harness.store import documents
from super_harness.store.ids import new_id
from super_harness.store.locks import locked
from super_harness.store.paths import StorePaths
from super_harness.store.yamlio import load_yaml


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


def add_tickets(plan_id: str, text: str, *, project: str | None, by: str) -> Batch:
    """Validate a YAML or JSON ticket list for an approved plan, then queue every ticket."""
    items = _parse_batch(text)
    paths = StorePaths.default()
    slug, plan_path = records.locate_plan(paths, plan_id, project)
    resolved = settings.load(paths, slug)
    for number, item in enumerate(items, 1):
        if item.importance.value not in resolved.workflows:
            raise UserError(f"ticket {number}: settings have no workflow {item.importance.value!r}")
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
                workflow=item.importance.value,
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
    records.record(paths, f"harness: ticket add {' '.join(new.id for new in made)}", *created)
    return Batch(plan.id, slug, made)


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
        f"harness plan approve {plan.id}"
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
    """True when every dependency is a ticket of this project in `done/`."""
    return all(dep in tickets and tickets[dep].meta.folder is Folder.done for dep in depends_on)


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
