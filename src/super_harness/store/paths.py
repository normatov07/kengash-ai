"""Where everything lives in the store (system spec §4.1)."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from super_harness.model import Folder

ENV_HOME = "HARNESS_HOME"


def harness_home() -> Path:
    """The store root: $HARNESS_HOME, else ~/.harness."""
    value = os.environ.get(ENV_HOME)
    return Path(value).expanduser() if value else Path.home() / ".harness"


@dataclass(frozen=True)
class ProjectPaths:
    root: Path

    @property
    def settings(self) -> Path:
        return self.root / "SETTINGS.md"

    @property
    def process(self) -> Path:
        return self.root / "PROCESS.md"

    @property
    def memory_link(self) -> Path:
        return self.root / "memory"

    @property
    def plans(self) -> Path:
        return self.root / "plans"

    @property
    def archive(self) -> Path:
        return self.root / "archive"

    def folder(self, folder: Folder) -> Path:
        return self.root / "tasks" / folder.value


@dataclass(frozen=True)
class StorePaths:
    home: Path

    @classmethod
    def default(cls) -> Self:
        return cls(harness_home().absolute())

    @property
    def registry(self) -> Path:
        return self.home / "registry.yaml"

    @property
    def memory(self) -> Path:
        return self.home / "memory"

    @property
    def defaults(self) -> Path:
        return self.home / "defaults"

    @property
    def projects(self) -> Path:
        return self.home / "projects"

    @property
    def journal(self) -> Path:
        return self.home / "journal"

    @property
    def runtime(self) -> Path:
        return self.home / "runtime"

    @property
    def locks(self) -> Path:
        return self.runtime / "locks"

    @property
    def slots(self) -> Path:
        return self.runtime / "slots.json"

    @property
    def claims(self) -> Path:
        return self.runtime / "claims.json"

    @property
    def workers(self) -> Path:
        return self.runtime / "workers"

    @property
    def ticket_states(self) -> Path:
        return self.runtime / "tickets"

    @property
    def conductors(self) -> Path:
        return self.runtime / "conductors"

    @property
    def logs(self) -> Path:
        return self.runtime / "logs"

    @property
    def worktrees(self) -> Path:
        return self.home / "worktrees"

    def worktree(self, slug: str, ticket_id: str) -> Path:
        return self.worktrees / slug / f"hrn-{ticket_id}"

    @property
    def trust(self) -> Path:
        return self.runtime / "trust.json"

    @property
    def flags(self) -> Path:
        return self.runtime / "flags"

    def project(self, slug: str) -> ProjectPaths:
        return ProjectPaths(self.projects / slug)
