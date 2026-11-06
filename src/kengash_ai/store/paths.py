"""Where everything lives in the store (system spec §4.1)."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from kengash_ai.model import Folder

ENV_HOME = "KENGASH_HOME"
LEGACY_ENV_HOME = "HARNESS_HOME"  # read until 0.3.0 (SP8 spec decision 2)
HOME_NAME = ".kengash"
LEGACY_HOME_NAME = ".harness"


def kengash_home() -> Path:
    """The store root: $KENGASH_HOME, else $HARNESS_HOME, else ~/.kengash."""
    value = os.environ.get(ENV_HOME) or os.environ.get(LEGACY_ENV_HOME)
    return Path(value).expanduser() if value else Path.home() / HOME_NAME


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
        return cls(kengash_home().absolute())

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
    def loops(self) -> Path:
        return self.runtime / "loops"

    @property
    def logs(self) -> Path:
        return self.runtime / "logs"

    @property
    def ui_file(self) -> Path:
        return self.runtime / "ui.json"

    @property
    def worktrees(self) -> Path:
        return self.home / "worktrees"

    def worktree(self, slug: str, ticket_id: str) -> Path:
        """`worktrees/<slug>/kg-<id>`; a ticket claimed before 0.2.0 keeps its `hrn-<id>`."""
        legacy = self.worktrees / slug / f"hrn-{ticket_id}"
        return legacy if legacy.is_dir() else self.worktrees / slug / f"kg-{ticket_id}"

    @property
    def trust(self) -> Path:
        return self.runtime / "trust.json"

    @property
    def flags(self) -> Path:
        return self.runtime / "flags"

    def project(self, slug: str) -> ProjectPaths:
        return ProjectPaths(self.projects / slug)
