"""Shared fixtures: an isolated store, a real git repo and a ticket factory."""

import json
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from super_harness.model import Doc, Ticket
from super_harness.ops import projects
from super_harness.store import StorePaths

NOW = datetime(2026, 10, 22, 9, 41, tzinfo=UTC)


def git(cwd: Path, *args: str) -> str:
    """Run git with a throwaway identity and return its stdout."""
    result = subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


@pytest.fixture
def run_git() -> Callable[..., str]:
    return git


@pytest.fixture
def store_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> StorePaths:
    home = tmp_path / "home" / ".harness"
    monkeypatch.setenv("HARNESS_HOME", str(home))
    return StorePaths(home)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "code" / "Payments API"
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    (path / "README.md").write_text("payments\n", encoding="utf-8")
    git(path, "add", ".")
    git(path, "commit", "-q", "-m", "init")
    return Path(git(path, "rev-parse", "--show-toplevel").strip())


@pytest.fixture
def make_ticket() -> Callable[..., Doc[Ticket]]:
    def factory(ticket_id: str = "7b55e0c1", **fields: Any) -> Doc[Ticket]:
        meta: dict[str, Any] = {
            "id": ticket_id,
            "uuid": uuid4(),
            "project": "payments-api",
            "plan": "a1b2c3d4",
            "title": "Rotate keys",
            "importance": "critical",
            "workflow": "critical",
            "status": "in_queue/ready",
            "loop_max": 6,
            "created": NOW,
            "updated": NOW,
        }
        return Doc(Ticket.model_validate(meta | fields), {"Scope": "Rotate keys."})

    return factory


@pytest.fixture
def registered_repo(store_paths: StorePaths, repo: Path) -> Path:
    """`repo`, registered in the test store as payments-api."""
    projects.init_project(repo)
    return repo


@pytest.fixture
def inside_registered_repo(registered_repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(registered_repo)
    return registered_repo


@pytest.fixture
def journal_events(store_paths: StorePaths) -> Callable[[], list[dict[str, Any]]]:
    """Read back every journal event written so far."""

    def read() -> list[dict[str, Any]]:
        return [
            json.loads(line)
            for path in sorted(store_paths.journal.glob("*.jsonl"))
            for line in path.read_text(encoding="utf-8").splitlines()
        ]

    return read
