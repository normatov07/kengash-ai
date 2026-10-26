"""Load, save, find and check plan and ticket files (system spec §4.4)."""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from kengash_ai.model import (
    PLAN_SECTIONS,
    TICKET_SECTIONS,
    Doc,
    Folder,
    Plan,
    Ticket,
    UserError,
)
from kengash_ai.store.files import atomic_write
from kengash_ai.store.frontmatter import parse, render
from kengash_ai.store.memo import Memo, digest
from kengash_ai.store.paths import ProjectPaths

Kind = Literal["plan", "ticket"]


# Each document parsed once per content (SP7 spec decision 1); callers get copies.
_plans: Memo[Doc[Plan]] = Memo(maxsize=1024)
_tickets: Memo[Doc[Ticket]] = Memo(maxsize=4096)


def load_plan(path: Path) -> Doc[Plan]:
    data = path.read_bytes()

    def make() -> Doc[Plan]:
        meta, sections = parse(data.decode("utf-8"), PLAN_SECTIONS)
        return Doc(Plan.model_validate(meta), sections)

    doc = _plans.get_or_make(digest(data), make)
    return Doc(doc.meta.model_copy(deep=True), dict(doc.sections))


def load_ticket(path: Path) -> Doc[Ticket]:
    data = path.read_bytes()

    def make() -> Doc[Ticket]:
        meta, sections = parse(data.decode("utf-8"), TICKET_SECTIONS)
        return Doc(Ticket.model_validate(meta), sections)

    doc = _tickets.get_or_make(digest(data), make)
    return Doc(doc.meta.model_copy(deep=True), dict(doc.sections))


def load_any(path: Path, kind: Kind) -> tuple[Plan | Ticket, dict[str, str]]:
    if kind == "plan":
        plan = load_plan(path)
        return plan.meta, plan.sections
    ticket = load_ticket(path)
    return ticket.meta, ticket.sections


def save_plan(project: ProjectPaths, doc: Doc[Plan]) -> Path:
    path = project.plans / f"{doc.meta.id}.md"
    atomic_write(path, render(_dump(doc.meta), doc.sections, PLAN_SECTIONS))
    return path


def save_ticket(project: ProjectPaths, doc: Doc[Ticket]) -> Path:
    """Write a ticket into the folder its status names; a copy elsewhere is moved first."""
    path = project.folder(doc.meta.folder) / f"{doc.meta.id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    current = find_ticket(project, doc.meta.id)
    if current is not None and current != path:
        os.replace(current, path)
    atomic_write(path, render(_dump(doc.meta), doc.sections, TICKET_SECTIONS))
    return path


def save_any(project: ProjectPaths, meta: Plan | Ticket, sections: dict[str, str]) -> Path:
    if isinstance(meta, Plan):
        return save_plan(project, Doc(meta, sections))
    return save_ticket(project, Doc(meta, sections))


def find_ticket(project: ProjectPaths, ticket_id: str) -> Path | None:
    for folder in Folder:
        path = project.folder(folder) / f"{ticket_id}.md"
        if path.exists():
            return path
    return None


def iter_documents(project: ProjectPaths) -> Iterator[tuple[Path, Kind]]:
    """Every plan and ticket file of a project, plans first."""
    for path in sorted(project.plans.glob("*.md")):
        yield path, "plan"
    for folder in Folder:
        for path in sorted(project.folder(folder).glob("*.md")):
            yield path, "ticket"


def check_document(path: Path, kind: Kind) -> str | None:
    """One line describing what is wrong with a document, or None when it is valid."""
    try:
        meta, _ = load_any(path, kind)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"]) or "frontmatter"
        return f"invalid {where}: {first['msg']}"
    except UserError as exc:
        return str(exc)
    if isinstance(meta, Ticket) and path.parent.name != meta.folder.value:
        return f"in {path.parent.name}/ but status says {meta.status}"
    return None


def _dump(meta: Plan | Ticket) -> dict[str, object]:
    return meta.model_dump(mode="json", exclude_none=True)
