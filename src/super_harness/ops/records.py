"""Find plans and tickets across projects, describe bad input, and record each change."""

import difflib
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from super_harness import journal
from super_harness.model import Doc, Event, Plan, Ticket, UserError
from super_harness.store import documents, storegit
from super_harness.store.paths import ProjectPaths, StorePaths
from super_harness.store.registry import load_registry


@dataclass
class Document:
    project: str
    path: Path
    meta: dict[str, Any]
    sections: dict[str, str]
    text: str


def scope(paths: StorePaths, project: str | None) -> list[str]:
    """`[project]` once the registry knows it, else every registered project."""
    registry = load_registry(paths)
    if project is None:
        return sorted(registry.projects)
    if project not in registry.projects:
        raise UserError(f"unknown project: {project}")
    return [project]


def locate_plan(paths: StorePaths, plan_id: str, project: str | None) -> tuple[str, Path]:
    found = [
        (slug, path)
        for slug in scope(paths, project)
        if (path := paths.project(slug).plans / f"{plan_id}.md").is_file()
    ]
    return _only("plan", plan_id, found)


def locate_ticket(paths: StorePaths, ticket_id: str, project: str | None) -> tuple[str, Path]:
    found: list[tuple[str, Path]] = []
    for slug in scope(paths, project):
        path = documents.find_ticket(paths.project(slug), ticket_id)
        if path is not None:
            found.append((slug, path))
    return _only("ticket", ticket_id, found)


def taken_ids(paths: StorePaths) -> set[str]:
    """Every plan and ticket id in the store, so new ids stay unique across projects."""
    if not paths.projects.is_dir():
        return set()
    return {
        path.stem
        for root in paths.projects.iterdir()
        if root.is_dir()
        for path, _ in documents.iter_documents(ProjectPaths(root))
    }


def project_tickets(paths: StorePaths, slug: str) -> dict[str, Doc[Ticket]]:
    """The project's valid tickets by id; `harness doctor` reports the invalid ones."""
    tickets: dict[str, Doc[Ticket]] = {}
    for path, kind in documents.iter_documents(paths.project(slug)):
        if kind == "ticket":
            try:
                doc = documents.load_ticket(path)
            except (UserError, ValidationError):
                continue
            tickets[doc.meta.id] = doc
    return tickets


def load_plan(path: Path) -> Doc[Plan]:
    try:
        return documents.load_plan(path)
    except ValidationError as exc:
        raise UserError(f"{path.name}: {describe(exc)}; run: harness doctor") from exc


def load_ticket(path: Path) -> Doc[Ticket]:
    try:
        return documents.load_ticket(path)
    except ValidationError as exc:
        raise UserError(f"{path.name}: {describe(exc)}; run: harness doctor") from exc


def document(slug: str, path: Path, doc: Doc[Plan] | Doc[Ticket]) -> Document:
    meta = doc.meta.model_dump(mode="json", exclude_none=True)
    return Document(slug, path, meta, doc.sections, path.read_text(encoding="utf-8"))


def describe(exc: ValidationError, prefix: str = "", known: Collection[str] = ()) -> str:
    """One line for the first problem, e.g. `ticket 2: scop: unknown field`."""
    errors = exc.errors()
    first = errors[0]
    where = ".".join(str(part) for part in first["loc"])
    if first["type"] == "extra_forbidden":
        hint = difflib.get_close_matches(where, list(known), n=1)
        message = "unknown field" + (f"; did you mean {hint[0]}?" if hint else "")
    else:
        message = first["msg"].removeprefix("Value error, ")
    more = f" (+{len(errors) - 1} more)" if len(errors) > 1 else ""
    head = f"{prefix}{where}: " if where else prefix
    return f"{head}{message}{more}"


def one_line(text: str, what: str) -> str:
    value = text.strip()
    if not value:
        raise UserError(f"{what} is empty")
    if len(value.splitlines()) > 1:
        raise UserError(f"{what} must be one line")
    return value


def record(paths: StorePaths, message: str, *events: Event) -> None:
    """Journal each event, then commit the store."""
    for event in events:
        journal.append(paths, event)
    storegit.commit_store(paths, message)


def _only(kind: str, item_id: str, found: list[tuple[str, Path]]) -> tuple[str, Path]:
    if not found:
        raise UserError(f"unknown {kind}: {item_id}")
    if len(found) > 1:
        names = ", ".join(slug for slug, _ in found)
        raise UserError(f"{kind} {item_id} is in several projects ({names}); pass --project")
    return found[0]
