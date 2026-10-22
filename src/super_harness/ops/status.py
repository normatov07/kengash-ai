"""Board summary: tickets per folder for each project, and the gates waiting on the user."""

from collections import Counter
from dataclasses import dataclass, field

from super_harness.model import Folder
from super_harness.ops import records
from super_harness.ops.workspace import OpenGate, open_gates
from super_harness.store.paths import StorePaths


@dataclass
class ProjectStatus:
    project: str
    folders: dict[str, int]
    statuses: dict[str, int]
    gates: list[OpenGate] = field(default_factory=list)


@dataclass
class Board:
    projects: list[ProjectStatus]


def board(project: str | None = None) -> Board:
    """Every registered project, or only the named one."""
    paths = StorePaths.default()
    found: list[ProjectStatus] = []
    for slug in records.scope(paths, project):
        statuses = Counter(doc.meta.status for doc in records.project_tickets(paths, slug).values())
        folders = {
            folder.value: sum(
                count for name, count in statuses.items() if name.startswith(f"{folder.value}/")
            )
            for folder in Folder
        }
        found.append(
            ProjectStatus(slug, folders, dict(sorted(statuses.items())), open_gates(paths, slug))
        )
    return Board(found)
