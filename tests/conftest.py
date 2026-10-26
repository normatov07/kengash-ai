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

from kengash_ai import gitops
from kengash_ai.model import Doc, Plan, Ticket, TicketState
from kengash_ai.ops import projects
from kengash_ai.store import StorePaths, documents, runtime
from kengash_ai.store.seed import ensure_store

NOW = datetime(2026, 10, 22, 9, 41, tzinfo=UTC)
FAKES = Path(__file__).parent / "fakes"
Events = Callable[[], list[dict[str, Any]]]


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
        shell: str | None = None,
    ) -> None:
        """Queue the next reply of `cli` (claude, codex or agy) to a non-status call."""
        queue = self.state / cli / "queue"
        queue.mkdir(parents=True, exist_ok=True)
        reply: dict[str, Any] = {"stdout": stdout, "stderr": stderr, "exit": exit, "sleep": sleep}
        if fixture is not None:
            reply["fixture"] = fixture
        reply["edits"] = edits or {}
        if shell is not None:
            reply["shell"] = shell
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

    def claude_output(self, structured: dict[str, Any]) -> str:
        """The recorded claude reply with `structured` as its output."""
        data = self.fixture_json("claude/review_new.json")
        data["structured_output"] = structured
        data["result"] = json.dumps(structured)
        return json.dumps(data)

    def codex_output(self, structured: dict[str, Any]) -> str:
        """The recorded codex resume events with `structured` as the agent message."""
        lines = [json.loads(line) for line in self.fixture("codex/work_resume.jsonl").splitlines()]
        for event in lines:
            if event.get("type") == "item.completed":
                event["item"]["text"] = json.dumps(structured)
        return "".join(json.dumps(event) + "\n" for event in lines)

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


@dataclass
class Engine:
    """A registered repo with plan a1b2c3d4 and ticket 7b55e0c1 claimed at its first step."""

    paths: StorePaths
    repo: Path
    slug: str = "payments-api"
    ticket_id: str = "7b55e0c1"

    @property
    def worktree(self) -> Path:
        return self.paths.worktree(self.slug, self.ticket_id)

    def ticket(self) -> Doc[Ticket]:
        path = documents.find_ticket(self.paths.project(self.slug), self.ticket_id)
        assert path is not None
        return documents.load_ticket(path)

    def state(self) -> TicketState:
        return runtime.load_ticket_state(self.paths, self.ticket_id)


@pytest.fixture
def engine(
    registered_repo: Path,
    store_paths: StorePaths,
    make_ticket: Callable[..., Doc[Ticket]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Engine:
    config = tmp_path / "gitconfig"
    config.write_text("[user]\n\tname = Dev\n\temail = dev@example.com\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    project = store_paths.project("payments-api")
    plan = Plan.model_validate(
        {
            "id": "a1b2c3d4",
            "uuid": uuid4(),
            "project": "payments-api",
            "title": "Webhook retries",
            "mode": "quick",
            "status": "ticketed",
            "tickets": ["7b55e0c1"],
            "created": NOW,
            "updated": NOW,
        }
    )
    documents.save_plan(project, Doc(plan, {"Goal": "Webhook deliveries retry with backoff."}))
    doc = make_ticket(
        importance="simple",
        workflow="simple",
        loop_max=3,
        status="in_process/under_planning",
        step="plan",
        branch="hrn/7b55e0c1",
    )
    doc.sections["Acceptance"] = "- [ ] retries 3 times"
    documents.save_ticket(project, doc)
    worktree = store_paths.worktree("payments-api", "7b55e0c1")
    gitops.ensure_worktree(registered_repo, worktree, "hrn/7b55e0c1", "main")
    return Engine(store_paths, registered_repo)


PINNED = "- ships small, reviews hard (pin)"
LONG_MEMORY = [
    "# MEMORY.md",
    "",
    "Global memory.",
    "",
    "## Working style",
    "",
    PINNED,
    "- ships small",
    "- small diffs",
    "- small PRs",
    "",
    "## Goals",
    "",
    "- payments first",
    "- payments come first",
    "",
    "## Preferences",
    "",
    "## Turned down",
]
COMPACTED = (
    "# MEMORY.md\n\nGlobal memory.\n\n## Working style\n\n"
    f"{PINNED}\n- small diffs and PRs\n\n## Goals\n\n- payments first\n\n"
    "## Preferences\n\n## Turned down\n"
)


@pytest.fixture
def long_memory(store_paths: StorePaths) -> Path:
    """A 19-line MEMORY.md over its 18-line cap; COMPACTED is a valid 16-line result."""
    ensure_store(store_paths)
    write_settings(store_paths, "memory.compact_at_lines: 18\n", slugs=(None,))
    path = store_paths.memory / "MEMORY.md"
    path.write_text("\n".join(LONG_MEMORY) + "\n", encoding="utf-8")
    return path
