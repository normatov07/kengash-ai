"""Shared fixtures: an isolated store, a real git repo, a ticket factory and fake CLIs."""

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from super_harness.model import Doc, Ticket
from super_harness.ops import projects
from super_harness.store import StorePaths

NOW = datetime(2026, 10, 22, 9, 41, tzinfo=UTC)
FAKES = Path(__file__).parent / "fakes"


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


def write_settings(
    paths: StorePaths, text: str, slugs: tuple[str | None, ...] = (None, "payments-api")
) -> None:
    """Replace each scope's SETTINGS.md with `text`; layers merge it over the package defaults."""
    for slug in slugs:
        target = paths.defaults / "SETTINGS.md" if slug is None else paths.project(slug).settings
        target.write_text(text, encoding="utf-8")


@dataclass
class FakeClis:
    """Drives the fake claude, codex and agy that come first on PATH in every test."""

    state: Path
    bin: Path
    queued: dict[str, int] = field(default_factory=dict)

    def queue(
        self,
        cli: str,
        *,
        fixture: str | None = None,
        stdout: str = "",
        stderr: str = "",
        exit: int = 0,
        edits: dict[str, str] | None = None,
        sleep: float = 0,
    ) -> None:
        """Queue the next reply of `cli` (claude, codex or agy) to a non-status call."""
        queue = self.state / cli / "queue"
        queue.mkdir(parents=True, exist_ok=True)
        reply: dict[str, Any] = {"stdout": stdout, "stderr": stderr, "exit": exit, "sleep": sleep}
        if fixture is not None:
            reply["fixture"] = fixture
        reply["edits"] = edits or {}
        number = self.queued.get(cli, 0)
        self.queued[cli] = number + 1
        (queue / f"{number:04d}.json").write_text(json.dumps(reply), encoding="utf-8")

    def calls(self, cli: str) -> list[dict[str, Any]]:
        """Recorded calls of `cli`: argv without the binary, working directory, watched env."""
        path = self.state / cli / "calls.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def fixture(self, name: str) -> str:
        return (FAKES / "fixtures" / name).read_text(encoding="utf-8")

    def fixture_json(self, name: str) -> Any:
        return json.loads(self.fixture(name))

    def hide(self, cli: str) -> None:
        (self.bin / cli).unlink()

    def sign_out(self, cli: str) -> None:
        (self.state / cli).mkdir(parents=True, exist_ok=True)
        (self.state / cli / "signed_out").touch()

    def auth_method(self, method: str) -> None:
        (self.state / "claude").mkdir(parents=True, exist_ok=True)
        (self.state / "claude" / "auth_method").write_text(method, encoding="utf-8")


@pytest.fixture(autouse=True)
def fake_clis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeClis:
    """Put the fakes first on PATH so no test ever runs a real provider CLI."""
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    for cli in ("claude", "codex", "agy"):
        (fake_bin / cli).symlink_to(FAKES / "bin" / cli)
    state = tmp_path / "fake-state"
    monkeypatch.setenv("HARNESS_FAKE_DIR", str(state))
    monkeypatch.setenv("HARNESS_FAKE_PYTHON", sys.executable)
    monkeypatch.setenv("HARNESS_FAKE_CLI", str(FAKES / "fake_cli.py"))
    git = shutil.which("git")
    venv = str(Path(sys.executable).parent)  # the harness and hrn console scripts
    dirs = [str(fake_bin), venv, *([str(Path(git).parent)] if git else []), "/usr/bin", "/bin"]
    monkeypatch.setenv("PATH", os.pathsep.join(dict.fromkeys(dirs)))
    return FakeClis(state, fake_bin)
