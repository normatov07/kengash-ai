# SP2 M1: Store Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every code block's `title` names the file it becomes.

**Goal:** A project can be registered in the `~/.harness` store, linked through `<repo>/.harness`, checked and repaired, re-linked after a move, and adopted from a real `.harness/` folder without data loss.

**Architecture:** `model` holds pydantic schemas and errors; `store` owns every file under `~/.harness` (atomic writes, frontmatter documents, registry, links, seeding, store git); `ops.projects` composes them into use cases; `cli` only formats `ops` results. Import-linter enforces `cli > ops > store > model`.

**Tech Stack:** Python ≥3.12, pydantic 2, ruamel.yaml, filelock, Typer, pytest, import-linter.

**Specs:** system spec §4.1–4.4; `docs/superpowers/specs/2026-10-22-sp2-store-cli-design.md` §2 items 1–7 and §3 rows `init`, `doctor`, `link`, `adopt`.

## Global Constraints

- Store root: `$HARNESS_HOME`, default `~/.harness`, mode 0700, itself a git repo ignoring `runtime/` and `worktrees/`.
- Store commits: `git -c user.name=harness -c user.email=harness@localhost -c commit.gpgsign=false -c core.hooksPath=/dev/null`; message `harness: <command> <ids>`.
- Every store write: temp file in the same real directory → fsync → `os.replace`.
- Link: `<repo>/.harness` is a directory symlink to `$HARNESS_HOME/projects/<slug>`; `/.harness` is added to the repo's `info/exclude`.
- Slug: lowercase, runs outside `[a-z0-9]` → `-`, trimmed, empty → `project`; duplicates `-2`, `-3`.
- Ids: uuid4; short id = first 8 hex digits; re-roll on collision.
- Exit codes: 0 ok · 1 error · 4 setup needed · 5 user decision.
- Output: one line per fact; `--json` prints the result dataclass as JSON.
- Tests: isolated `HARNESS_HOME` under `tmp_path`, real temporary git repos, no network.
- Every commit touching `src/super_harness/<m>` also touches `docs/modules/<m>/README.md`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## File Structure

| Path | Responsibility |
|---|---|
| `src/super_harness/model/{__init__,core,errors,documents,registry}.py` | schemas, enums, errors |
| `src/super_harness/store/paths.py` | `StorePaths`, `ProjectPaths`, `harness_home()` |
| `src/super_harness/store/{files,yamlio,ids,locks}.py` | atomic writes, YAML, ids, locks |
| `src/super_harness/store/frontmatter.py` | parse/render documents with escaping |
| `src/super_harness/store/documents.py` | plan/ticket load, save, find, move, check |
| `src/super_harness/store/{registry,links,seed,storegit}.py` | registry, symlinks, seeding, store git |
| `src/super_harness/store/defaults/*.md` | seed files copied once |
| `src/super_harness/ops/projects.py` | init, doctor, relink, adopt |
| `src/super_harness/cli.py` | `init`, `doctor`, `link`, `adopt` commands |
| `tests/conftest.py` | `store_paths`, `repo`, `make_ticket`, `run_git` fixtures |

---

### Task 1: Dependencies

**Files:** Modify `pyproject.toml`; regenerate `uv.lock`.

- [ ] **Step 1: Add dependencies**

Run: `uv add 'pydantic>=2.9' 'ruamel.yaml>=0.18' 'filelock>=3.16' && uv add --dev 'import-linter>=2.1'`

- [ ] **Step 2: Enable the pydantic mypy plugin** — in `[tool.mypy]` add `plugins = ["pydantic.mypy"]`. If mypy later reports missing stubs for `ruamel`, add:

```toml
[[tool.mypy.overrides]]
module = ["ruamel.*"]
ignore_missing_imports = true
```

- [ ] **Step 3: Verify and commit**

Run: `make check` → exit 0. Then:

```bash
git add pyproject.toml uv.lock
git commit -m "build: add pydantic, ruamel.yaml, filelock and import-linter" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `model` package

**Files:** Create `src/super_harness/model/{__init__,core,errors,documents,registry}.py`, `tests/test_model.py`, `docs/modules/model/README.md`.

**Interfaces — Produces:** `Folder`, `Gate`, `Importance` (StrEnum), `ShortId`, `utc_now() -> datetime`; `HarnessError(exit_code=1)`, `UserError(1)`, `NeedsSetup(4)`, `NeedsUser(5)`; `Plan`, `PlanMode`, `PlanStatus`, `Review`, `SessionRef`, `Ticket` (with `.folder`), `Doc[M]` (`meta`, `sections`), `PLAN_SECTIONS`, `TICKET_SECTIONS`; `Registry`, `ProjectEntry`.

- [ ] **Step 1: Write the failing test**

```python title="tests/test_model.py"
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from super_harness.model import Folder, Plan, PlanMode, PlanStatus, Ticket

NOW = datetime(2026, 10, 22, 9, 41, tzinfo=UTC)


def ticket(**overrides: Any) -> Ticket:
    fields: dict[str, Any] = {
        "id": "7b55e0c1",
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
    return Ticket.model_validate(fields | overrides)


def test_ticket_folder_comes_from_status() -> None:
    assert ticket(status="in_process/under_review").folder is Folder.in_process


@pytest.mark.parametrize("status", ["queued", "in_queue", "elsewhere/ready", "in_queue/Ready"])
def test_ticket_rejects_malformed_status(status: str) -> None:
    with pytest.raises(ValidationError, match="status must be"):
        ticket(status=status)


def test_status_is_validated_on_assignment() -> None:
    item = ticket()
    with pytest.raises(ValidationError, match="status must be"):
        item.status = "done"


def test_ticket_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ticket(colour="blue")


def test_short_ids_are_eight_lowercase_hex_digits() -> None:
    with pytest.raises(ValidationError):
        ticket(id="7B55E0C1")


def test_plan_defaults() -> None:
    plan = Plan(
        id="a1b2c3d4",
        uuid=uuid4(),
        project="payments-api",
        title="Rotatable keys",
        mode=PlanMode.grill,
        status=PlanStatus.grilling,
        created=NOW,
        updated=NOW,
    )
    assert (plan.review.round, plan.review.max, plan.tickets, plan.milestone) == (0, 2, [], 1)
```

- [ ] **Step 2: Run it and watch it fail** — `uv run pytest tests/test_model.py` → `ModuleNotFoundError: No module named 'super_harness.model'`.

- [ ] **Step 3: Write the package**

```python title="src/super_harness/model/core.py"
"""Primitive types shared by every schema."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import StringConstraints

ShortId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{8}$")]


class Importance(StrEnum):
    simple = "simple"
    standard = "standard"
    critical = "critical"


class Gate(StrEnum):
    afk = "afk"
    hitl = "hitl"


class Folder(StrEnum):
    in_queue = "in_queue"
    in_process = "in_process"
    done = "done"


def utc_now() -> datetime:
    """Current UTC time at second precision, as stored in frontmatter."""
    return datetime.now(UTC).replace(microsecond=0)
```

```python title="src/super_harness/model/errors.py"
"""Errors that carry the exit code the CLI returns (system spec §6)."""


class HarnessError(Exception):
    """Base error: a one-line message plus an exit code."""

    exit_code = 1


class UserError(HarnessError):
    """Bad input, or a state the requested command cannot act on."""


class NeedsSetup(HarnessError):
    """Missing install, sign-in or init, or a folder that needs adopting."""

    exit_code = 4


class NeedsUser(HarnessError):
    """A decision only the user can make."""

    exit_code = 5
```

```python title="src/super_harness/model/documents.py"
"""Plan and ticket frontmatter schemas, and the document wrapper (system spec §4.4)."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from super_harness.model.core import Folder, Gate, Importance, ShortId

PLAN_SECTIONS = (
    "Prompt",
    "Goal",
    "Decisions",
    "Assumptions",
    "Scope",
    "Out of scope",
    "Design",
    "Acceptance",
    "Test seams",
    "Risks",
    "Milestones",
    "Review log",
)
TICKET_SECTIONS = ("Scope", "Acceptance", "Handoff", "Findings", "Log")
_STATUS = re.compile(r"^(in_queue|in_process|done)/[a-z_]+$")


class PlanMode(StrEnum):
    grill = "grill"
    direct = "direct"
    quick = "quick"


class PlanStatus(StrEnum):
    grilling = "grilling"
    draft = "draft"
    in_review = "in_review"
    approved = "approved"
    ticketed = "ticketed"
    rejected = "rejected"


class _Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Review(_Schema):
    round: int = 0
    max: int = 2
    verdict: Literal["pass", "fail"] | None = None
    reviewer: str | None = None
    skipped: bool = False


class Plan(_Schema):
    id: ShortId
    uuid: UUID
    project: str
    title: str
    mode: PlanMode
    status: PlanStatus
    review: Review = Field(default_factory=Review)
    milestone: int = 1
    tickets: list[ShortId] = Field(default_factory=list)
    created: datetime
    updated: datetime


class SessionRef(_Schema):
    provider: str
    model: str = "default"
    id: str


class Ticket(_Schema):
    id: ShortId
    uuid: UUID
    project: str
    plan: ShortId
    title: str
    importance: Importance
    workflow: str
    status: str
    gate: Gate = Gate.afk
    loop: int = 1
    loop_max: int
    tokens: int = 0
    depends_on: list[ShortId] = Field(default_factory=list)
    touches: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    branch: str | None = None
    sessions: dict[str, SessionRef] = Field(default_factory=dict)
    created: datetime
    updated: datetime

    @field_validator("status")
    @classmethod
    def _status_shape(cls, value: str) -> str:
        if not _STATUS.match(value):
            raise ValueError("status must be '<in_queue|in_process|done>/<sub_status>'")
        return value

    @property
    def folder(self) -> Folder:
        return Folder(self.status.split("/", 1)[0])


@dataclass
class Doc[M: BaseModel]:
    """A stored document: frontmatter model plus Markdown sections in file order."""

    meta: M
    sections: dict[str, str] = field(default_factory=dict)
```

```python title="src/super_harness/model/registry.py"
"""registry.yaml: the projects the store knows (system spec §4.1)."""

from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ProjectEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    path: Path
    base: str = "main"
    added: date


class Registry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projects: dict[str, ProjectEntry] = Field(default_factory=dict)
```

```python title="src/super_harness/model/__init__.py"
"""Schemas and errors shared by every unit; no I/O and no harness imports."""

from super_harness.model.core import Folder, Gate, Importance, ShortId, utc_now
from super_harness.model.documents import (
    PLAN_SECTIONS,
    TICKET_SECTIONS,
    Doc,
    Plan,
    PlanMode,
    PlanStatus,
    Review,
    SessionRef,
    Ticket,
)
from super_harness.model.errors import HarnessError, NeedsSetup, NeedsUser, UserError
from super_harness.model.registry import ProjectEntry, Registry

__all__ = [
    "PLAN_SECTIONS",
    "TICKET_SECTIONS",
    "Doc",
    "Folder",
    "Gate",
    "HarnessError",
    "Importance",
    "NeedsSetup",
    "NeedsUser",
    "Plan",
    "PlanMode",
    "PlanStatus",
    "ProjectEntry",
    "Registry",
    "Review",
    "SessionRef",
    "ShortId",
    "Ticket",
    "UserError",
    "utc_now",
]
```

- [ ] **Step 4: Run the tests** — `uv run pytest tests/test_model.py` → `9 passed`.

- [ ] **Step 5: Write the module doc**

```markdown title="docs/modules/model/README.md"
# model

## Purpose

Pydantic schemas and error types that every other unit shares. No I/O and no imports from other harness units.

## Interface

- `Plan`, `Ticket`, `Review`, `SessionRef`, `PlanMode`, `PlanStatus`: frontmatter schemas (system spec §4.4). Unknown keys are rejected and assignments are validated.
- `Doc[M]`: a frontmatter model plus ordered Markdown sections; `PLAN_SECTIONS` and `TICKET_SECTIONS` name them.
- `Registry`, `ProjectEntry`: `registry.yaml`.
- `Importance`, `Gate`, `Folder`, `ShortId`, `utc_now()`.
- Errors carry exit codes: `HarnessError` and `UserError` 1, `NeedsSetup` 4, `NeedsUser` 5.

## Invariants

- `Ticket.status` is `<in_queue|in_process|done>/<sub_status>`; `Ticket.folder` derives from it.
- Short ids are 8 lowercase hex digits: the first 8 of a uuid4.
- Timestamps are UTC at second precision.

## Changes

- 2026-10-22: plan, ticket and registry schemas, error types (SP2 M1).
```

- [ ] **Step 6: Lint and commit** — `uv run ruff format . && uv run ruff check . && uv run mypy`, then:

```bash
git add src/super_harness/model tests/test_model.py docs/modules/model
git commit -m "feat(model): plan, ticket and registry schemas with error types" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `store` package

**Files:** Create `src/super_harness/store/{__init__,paths,files,yamlio,ids,locks,storegit,registry,frontmatter,documents,links,seed}.py`, `src/super_harness/store/defaults/{SETTINGS,PROCESS,MEMORY,DECISIONS}.md`, `tests/conftest.py`, `tests/test_store_basics.py`, `tests/test_frontmatter.py`, `tests/test_documents.py`, `tests/test_links.py`, `docs/modules/store/README.md`.

**Interfaces — Consumes:** Task 2. **Produces:** `StorePaths(home)` with `.default()`, `.registry`, `.memory`, `.defaults`, `.projects`, `.journal`, `.runtime`, `.locks`, `.project(slug) -> ProjectPaths`; `ProjectPaths(root)` with `.settings`, `.process`, `.memory_link`, `.plans`, `.archive`, `.folder(Folder)`; `atomic_write(path, text)`; `load_yaml(text, source)`, `dump_yaml(data)`; `new_id(taken) -> (str, UUID)`; `locked(path, timeout=30.0)`; `storegit.ensure_repo(home)`, `storegit.commit(home, message) -> bool`, `storegit.commit_store(paths, message) -> bool`; `load_registry(paths)`, `save_registry(paths, registry)`, `slugify(name)`, `unique_slug(base, taken)`, `slug_for_path(registry, path)`; `parse(text, names) -> (dict, dict)`, `render(meta, sections, names) -> str`; `documents.load_plan|load_ticket|load_any|save_plan|save_ticket|save_any|find_ticket|iter_documents|check_document`, `Kind = Literal["plan", "ticket"]`; `links.LINK`, `LinkState`, `link_state`, `obstruction`, `make_link`, `ensure_excluded`, `is_excluded`; `seed.ensure_store(paths)`, `seed.ensure_project(paths, slug) -> ProjectPaths`.

- [ ] **Step 1: Write the shared fixtures**

```python title="tests/conftest.py"
"""Shared fixtures: an isolated store, a real git repo and a ticket factory."""

import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from super_harness.model import Doc, Ticket
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
```

- [ ] **Step 2: Write the failing tests**

```python title="tests/test_store_basics.py"
import os
from collections.abc import Callable
from datetime import date
from pathlib import Path
from uuid import UUID

import pytest

from super_harness.model import HarnessError, ProjectEntry, Registry
from super_harness.store import StorePaths, storegit
from super_harness.store.files import atomic_write
from super_harness.store.ids import new_id
from super_harness.store.locks import locked
from super_harness.store.registry import load_registry, save_registry, slugify, unique_slug


def test_atomic_write_replaces_content_without_leftovers(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "file.md"
    atomic_write(target, "one")
    atomic_write(target, "two")
    assert target.read_text(encoding="utf-8") == "two"
    assert os.listdir(target.parent) == ["file.md"]


def test_atomic_write_through_a_directory_symlink_keeps_the_link(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "link").symlink_to(real, target_is_directory=True)
    atomic_write(tmp_path / "link" / "file.md", "via link")
    assert (tmp_path / "link").is_symlink()
    assert (real / "file.md").read_text(encoding="utf-8") == "via link"


def test_new_id_rerolls_a_taken_short_id(monkeypatch: pytest.MonkeyPatch) -> None:
    taken = UUID("7b55e0c1-0000-4000-8000-000000000000")
    free = UUID("a91b3d07-0000-4000-8000-000000000000")
    monkeypatch.setattr("super_harness.store.ids.uuid4", iter([taken, free]).__next__)
    assert new_id({"7b55e0c1"}) == ("a91b3d07", free)


def test_lock_times_out_with_a_clear_error(tmp_path: Path) -> None:
    lock_file = tmp_path / "locks" / "x.lock"
    with (
        locked(lock_file),
        pytest.raises(HarnessError, match=r"store busy: x\.lock"),
        locked(lock_file, timeout=0.05),
    ):
        pass


@pytest.mark.parametrize(
    ("name", "slug"),
    [("Payments API", "payments-api"), ("web_dashboard", "web-dashboard"), ("--", "project")],
)
def test_slugify(name: str, slug: str) -> None:
    assert slugify(name) == slug


def test_unique_slug_appends_a_counter() -> None:
    assert unique_slug("app", {"app", "app-2"}) == "app-3"


def test_registry_round_trip(store_paths: StorePaths) -> None:
    registry = Registry(
        projects={"app": ProjectEntry(path=Path("/code/app"), added=date(2026, 10, 22))}
    )
    save_registry(store_paths, registry)
    assert load_registry(store_paths) == registry


def test_store_commits_ignore_runtime_and_skip_empty_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, run_git: Callable[..., str]
) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "absent-gitconfig"))
    home = tmp_path / "store"
    home.mkdir()
    storegit.ensure_repo(home)
    (home / "runtime").mkdir()
    (home / "runtime" / "pid").write_text("1", encoding="utf-8")
    (home / "registry.yaml").write_text("projects: {}\n", encoding="utf-8")
    assert storegit.commit(home, "harness: one") is True
    assert storegit.commit(home, "harness: none") is False
    assert run_git(home, "ls-files").split() == [".gitignore", "registry.yaml"]
```

```python title="tests/test_frontmatter.py"
import pytest

from super_harness.model import TICKET_SECTIONS, UserError
from super_harness.store.frontmatter import parse, render

NAMES = TICKET_SECTIONS
EMPTY = dict.fromkeys(NAMES, "")


def test_round_trip_keeps_meta_and_sections() -> None:
    meta = {"id": "7b55e0c1", "depends_on": ["a91b3d07"], "loop": 2}
    sections = EMPTY | {"Scope": "Rotate keys.\n\nWith overlap.", "Log": "- 09:41 plan"}
    assert parse(render(meta, sections, NAMES), NAMES) == (meta, sections)


def test_render_keeps_key_order_and_flow_lists() -> None:
    meta = {"id": "7b55e0c1", "depends_on": ["a91b3d07"], "branch": "hrn/7b55e0c1"}
    text = render(meta, {}, NAMES)
    assert text.startswith("---\nid: 7b55e0c1\ndepends_on: [a91b3d07]\nbranch: hrn/7b55e0c1\n---\n")


def test_unknown_headings_stay_inside_a_section() -> None:
    sections = EMPTY | {"Scope": "## Background\nkept as text"}
    assert parse(render({}, sections, NAMES), NAMES)[1]["Scope"] == "## Background\nkept as text"


def test_known_headings_inside_content_are_escaped() -> None:
    tricky = "line\n## Log\n\\## Log"
    text = render({}, EMPTY | {"Scope": tricky}, NAMES)
    assert "\n\\## Log\n" in text
    assert parse(text, NAMES)[1]["Scope"] == tricky


def test_unknown_section_names_are_refused() -> None:
    with pytest.raises(UserError, match="unknown sections: Notes"):
        render({}, {"Notes": "x"}, NAMES)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("no frontmatter", "no frontmatter"),
        ("---\nid: x\n", "not closed"),
        ("---\n- a\n---\n", "not a mapping"),
        ("---\nid: [unclosed\n---\n", "invalid YAML"),
    ],
)
def test_bad_frontmatter_is_a_user_error(text: str, message: str) -> None:
    with pytest.raises(UserError, match=message):
        parse(text, NAMES)
```

```python title="tests/test_documents.py"
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from super_harness.model import Doc, Folder, Plan, PlanMode, PlanStatus, Ticket
from super_harness.store import documents
from super_harness.store.paths import ProjectPaths

MakeTicket = Callable[..., Doc[Ticket]]
NOW = datetime(2026, 10, 22, 9, 41, tzinfo=UTC)


def test_ticket_round_trip(tmp_path: Path, make_ticket: MakeTicket) -> None:
    project = ProjectPaths(tmp_path)
    doc = make_ticket()
    path = documents.save_ticket(project, doc)
    assert path == project.folder(Folder.in_queue) / "7b55e0c1.md"
    loaded = documents.load_ticket(path)
    assert loaded.meta == doc.meta
    assert loaded.sections["Scope"] == "Rotate keys."


def test_saving_a_new_status_moves_the_file(tmp_path: Path, make_ticket: MakeTicket) -> None:
    project = ProjectPaths(tmp_path)
    doc = make_ticket()
    documents.save_ticket(project, doc)
    doc.meta.status = "in_process/under_planning"
    path = documents.save_ticket(project, doc)
    assert path.parent == project.folder(Folder.in_process)
    assert documents.find_ticket(project, "7b55e0c1") == path
    assert not (project.folder(Folder.in_queue) / "7b55e0c1.md").exists()


def test_plan_round_trip(tmp_path: Path) -> None:
    project = ProjectPaths(tmp_path)
    plan = Plan(
        id="a1b2c3d4",
        uuid=uuid4(),
        project="payments-api",
        title="Rotatable keys",
        mode=PlanMode.direct,
        status=PlanStatus.draft,
        created=NOW,
        updated=NOW,
    )
    prompt = "Make keys rotatable.\n## Goal\nas the user typed it"
    path = documents.save_plan(project, Doc(plan, {"Prompt": prompt}))
    loaded = documents.load_plan(path)
    assert loaded.meta == plan
    assert loaded.sections["Prompt"] == prompt


def test_check_document_reports_problems(tmp_path: Path, make_ticket: MakeTicket) -> None:
    project = ProjectPaths(tmp_path)
    path = documents.save_ticket(project, make_ticket())
    assert documents.check_document(path, "ticket") is None
    moved = project.folder(Folder.done) / path.name
    moved.parent.mkdir(parents=True)
    path.rename(moved)
    assert documents.check_document(moved, "ticket") == "in done/ but status says in_queue/ready"
    moved.write_text("---\nid: nope\n---\n", encoding="utf-8")
    problem = documents.check_document(moved, "ticket")
    assert problem is not None
    assert problem.startswith("invalid id: ")
```

```python title="tests/test_links.py"
from pathlib import Path

from super_harness.store import links


def test_link_states(tmp_path: Path) -> None:
    repo, target, other = tmp_path / "repo", tmp_path / "store", tmp_path / "other"
    repo.mkdir()
    target.mkdir()
    assert links.link_state(repo, target) is links.LinkState.missing
    links.make_link(repo, target)
    assert links.link_state(repo, target) is links.LinkState.ok
    assert links.link_state(repo, other) is links.LinkState.wrong
    links.make_link(repo, other)
    assert links.link_state(repo, other) is links.LinkState.ok


def test_real_folder_and_file_are_obstructions(tmp_path: Path) -> None:
    (tmp_path / "a" / ".harness").mkdir(parents=True)
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / ".harness").write_text("x", encoding="utf-8")
    assert links.link_state(tmp_path / "a", tmp_path) is links.LinkState.real_dir
    assert links.obstruction(tmp_path / "b") is links.LinkState.blocked
    assert links.obstruction(tmp_path) is None


def test_exclude_entry_is_added_once(repo: Path) -> None:
    assert links.is_excluded(repo) is False
    assert links.ensure_excluded(repo) is True
    assert links.ensure_excluded(repo) is True
    exclude = repo / ".git" / "info" / "exclude"
    assert exclude.read_text(encoding="utf-8").splitlines().count("/.harness") == 1
    assert links.is_excluded(repo) is True


def test_plain_folder_has_no_exclude_file(tmp_path: Path) -> None:
    assert links.ensure_excluded(tmp_path) is False
    assert links.is_excluded(tmp_path) is None
```

- [ ] **Step 3: Run them and watch them fail** — `uv run pytest tests/test_store_basics.py tests/test_frontmatter.py tests/test_documents.py tests/test_links.py` → errors `No module named 'super_harness.store'`.

- [ ] **Step 4: Write the store modules**

```python title="src/super_harness/store/paths.py"
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

    def project(self, slug: str) -> ProjectPaths:
        return ProjectPaths(self.projects / slug)
```

```python title="src/super_harness/store/files.py"
"""Atomic file writes: temp file in the same directory, fsync, rename."""

import os
import tempfile
from pathlib import Path


def atomic_write(path: Path, text: str) -> None:
    """Replace `path` with `text`; readers see the old or the new file, never a mix."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
```

```python title="src/super_harness/store/yamlio.py"
"""YAML in and out: safe loading, readable round-trip dumping."""

from io import StringIO
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from super_harness.model import UserError


def load_yaml(text: str, source: str) -> Any:
    """Parse YAML with the safe loader; errors become a UserError naming `source`."""
    try:
        return YAML(typ="safe", pure=True).load(text)
    except YAMLError as exc:
        problem = getattr(exc, "problem", None) or type(exc).__name__
        raise UserError(f"{source}: invalid YAML: {problem}") from exc


def dump_yaml(data: Any) -> str:
    """Block style for mappings, flow style for leaf lists and maps, key order kept."""
    yaml = YAML()
    yaml.default_flow_style = None
    yaml.width = 4096
    buffer = StringIO()
    yaml.dump(data, buffer)
    return buffer.getvalue()
```

```python title="src/super_harness/store/ids.py"
"""Plan and ticket ids: uuid4, with its first 8 hex digits as the short id."""

from collections.abc import Container
from uuid import UUID, uuid4


def new_id(taken: Container[str]) -> tuple[str, UUID]:
    """Return a fresh (short id, uuid), re-rolling while the short id is taken."""
    for _ in range(64):
        value = uuid4()
        if value.hex[:8] not in taken:
            return value.hex[:8], value
    raise RuntimeError("no free short id after 64 attempts")
```

```python title="src/super_harness/store/locks.py"
"""Inter-process locks under runtime/locks (system spec §4.3)."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock, Timeout

from super_harness.model import HarnessError


@contextmanager
def locked(path: Path, timeout: float = 30.0) -> Iterator[None]:
    """Hold an exclusive lock on `path` for the duration of the block."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(path, timeout=timeout)
    try:
        lock.acquire()
    except Timeout as exc:
        message = f"store busy: {path.name} held by another process for {timeout:g}s"
        raise HarnessError(message) from exc
    try:
        yield
    finally:
        lock.release()
```

```python title="src/super_harness/store/storegit.py"
"""The store's own git history: every state change becomes a commit (system spec §4.3)."""

import subprocess
from pathlib import Path

from super_harness.model import HarnessError
from super_harness.store.locks import locked
from super_harness.store.paths import StorePaths

IDENTITY = (
    "-c",
    "user.name=harness",
    "-c",
    "user.email=harness@localhost",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "core.hooksPath=/dev/null",
)
IGNORED = "runtime/\nworktrees/\n"


def _git(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *IDENTITY, *args], cwd=home, capture_output=True, text=True, check=False
    )


def ensure_repo(home: Path) -> None:
    """Make `home` a git repo that ignores runtime state and worktrees."""
    if not (home / ".git").exists():
        result = _git(home, "init", "-q", "-b", "main")
        if result.returncode != 0:
            raise HarnessError(f"store git init failed: {result.stderr.strip()}")
    ignore = home / ".gitignore"
    if not ignore.exists():
        ignore.write_text(IGNORED, encoding="utf-8")


def commit(home: Path, message: str) -> bool:
    """Commit every change under `home`; False when there was nothing to commit."""
    _git(home, "add", "-A")
    if _git(home, "diff", "--cached", "--quiet").returncode == 0:
        return False
    result = _git(home, "commit", "-q", "-m", message)
    if result.returncode != 0:
        raise HarnessError(f"store commit failed: {result.stderr.strip()}")
    return True


def commit_store(paths: StorePaths, message: str) -> bool:
    """Commit the store under its git lock, so concurrent commands never collide."""
    with locked(paths.locks / "git.lock"):
        return commit(paths.home, message)
```

```python title="src/super_harness/store/registry.py"
"""registry.yaml: project slug → repo path (system spec §4.1)."""

import re
from collections.abc import Collection
from pathlib import Path

from super_harness.model import Registry
from super_harness.store.files import atomic_write
from super_harness.store.paths import StorePaths
from super_harness.store.yamlio import dump_yaml, load_yaml


def load_registry(paths: StorePaths) -> Registry:
    if not paths.registry.exists():
        return Registry()
    data = load_yaml(paths.registry.read_text(encoding="utf-8"), "registry.yaml")
    return Registry.model_validate(data or {})


def save_registry(paths: StorePaths, registry: Registry) -> None:
    atomic_write(paths.registry, dump_yaml(registry.model_dump(mode="json")))


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"


def unique_slug(base: str, taken: Collection[str]) -> str:
    slug, counter = base, 2
    while slug in taken:
        slug, counter = f"{base}-{counter}", counter + 1
    return slug


def slug_for_path(registry: Registry, path: Path) -> str | None:
    for slug, entry in registry.projects.items():
        if entry.path == path:
            return slug
    return None
```

```python title="src/super_harness/store/frontmatter.py"
"""Markdown documents with YAML frontmatter and `## ` sections (system spec §4.4).

A content line that would read as a known heading is written with one extra leading
backslash and restored on read, so a verbatim prompt can never split a document.
"""

from collections.abc import Container, Sequence
from typing import Any

from super_harness.model import UserError
from super_harness.store.yamlio import dump_yaml, load_yaml

FENCE = "---\n"


def parse(text: str, names: Sequence[str]) -> tuple[dict[str, Any], dict[str, str]]:
    """Split a document into its frontmatter mapping and its known sections."""
    if not text.startswith(FENCE):
        raise UserError("document has no frontmatter")
    end = text.find("\n" + FENCE, len(FENCE) - 1)
    if end < 0:
        raise UserError("frontmatter is not closed with ---")
    meta = load_yaml(text[len(FENCE) : end + 1], "frontmatter") or {}
    if not isinstance(meta, dict):
        raise UserError("frontmatter is not a mapping")
    return meta, _split(text[end + 1 + len(FENCE) :], names)


def render(meta: dict[str, Any], sections: dict[str, str], names: Sequence[str]) -> str:
    """Write the frontmatter, then every known section in order; empty ones as bare headings."""
    unknown = sorted(set(sections) - set(names))
    if unknown:
        raise UserError(f"unknown sections: {', '.join(unknown)}")
    parts = [FENCE, dump_yaml(meta) if meta else "", FENCE]
    for name in names:
        parts.append(f"\n## {name}\n")
        text = sections.get(name, "").strip("\n")
        if text:
            parts.append(_escape(text, names) + "\n")
    return "".join(parts)


def _split(body: str, names: Sequence[str]) -> dict[str, str]:
    headings = {f"## {name}": name for name in names}
    sections: dict[str, str] = {}
    current: str | None = None
    lines: list[str] = []
    for line in body.split("\n"):
        if line in headings:
            if current is not None:
                sections[current] = _unescape(lines, headings)
            current, lines = headings[line], []
        elif current is not None:
            lines.append(line)
    if current is not None:
        sections[current] = _unescape(lines, headings)
    return sections


def _heading_like(line: str, headings: Container[str]) -> bool:
    return line.lstrip("\\") in headings


def _escape(text: str, names: Sequence[str]) -> str:
    headings = {f"## {name}" for name in names}
    return "\n".join(
        "\\" + line if _heading_like(line, headings) else line for line in text.split("\n")
    )


def _unescape(lines: list[str], headings: Container[str]) -> str:
    restored = [
        line[1:] if line.startswith("\\") and _heading_like(line, headings) else line
        for line in lines
    ]
    return "\n".join(restored).strip("\n")
```

```python title="src/super_harness/store/documents.py"
"""Load, save, find and check plan and ticket files (system spec §4.4)."""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from super_harness.model import (
    PLAN_SECTIONS,
    TICKET_SECTIONS,
    Doc,
    Folder,
    Plan,
    Ticket,
    UserError,
)
from super_harness.store.files import atomic_write
from super_harness.store.frontmatter import parse, render
from super_harness.store.paths import ProjectPaths

Kind = Literal["plan", "ticket"]


def load_plan(path: Path) -> Doc[Plan]:
    meta, sections = parse(path.read_text(encoding="utf-8"), PLAN_SECTIONS)
    return Doc(Plan.model_validate(meta), sections)


def load_ticket(path: Path) -> Doc[Ticket]:
    meta, sections = parse(path.read_text(encoding="utf-8"), TICKET_SECTIONS)
    return Doc(Ticket.model_validate(meta), sections)


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
```

```python title="src/super_harness/store/links.py"
"""The per-repo `.harness` directory symlink into the store (system spec §4.2)."""

import os
import subprocess
from enum import StrEnum
from pathlib import Path

LINK = ".harness"
EXCLUDE_ENTRY = "/.harness"


class LinkState(StrEnum):
    ok = "ok"
    missing = "missing"
    wrong = "points elsewhere"
    real_dir = "real folder"
    blocked = "blocked by a file"


def obstruction(repo: Path) -> LinkState | None:
    """`real_dir` or `blocked` when something other than a symlink sits at `.harness`."""
    link = repo / LINK
    if link.is_symlink() or not link.exists():
        return None
    return LinkState.real_dir if link.is_dir() else LinkState.blocked


def link_state(repo: Path, target: Path) -> LinkState:
    link = repo / LINK
    if link.is_symlink():
        return LinkState.ok if Path(os.readlink(link)) == target else LinkState.wrong
    return obstruction(repo) or LinkState.missing


def make_link(repo: Path, target: Path) -> None:
    """Point `<repo>/.harness` at `target`, replacing a stale symlink."""
    link = repo / LINK
    if link.is_symlink():
        link.unlink()
    link.symlink_to(target, target_is_directory=True)


def _exclude_file(repo: Path) -> Path | None:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "rev-parse",
            "--path-format=absolute",
            "--git-path",
            "info/exclude",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return Path(result.stdout.strip()) if result.returncode == 0 else None


def is_excluded(repo: Path) -> bool | None:
    """Whether info/exclude lists `/.harness`; None when `repo` is not a git work tree."""
    path = _exclude_file(repo)
    if path is None:
        return None
    return path.exists() and EXCLUDE_ENTRY in path.read_text(encoding="utf-8").splitlines()


def ensure_excluded(repo: Path) -> bool:
    """Add `/.harness` to info/exclude once; False when `repo` is not a git work tree."""
    path = _exclude_file(repo)
    if path is None:
        return False
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    if EXCLUDE_ENTRY not in lines:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join([*lines, EXCLUDE_ENTRY]) + "\n", encoding="utf-8")
    return True
```

```python title="src/super_harness/store/seed.py"
"""Create the store and project folders, seeding default files once (system spec §4.1)."""

from importlib import resources
from pathlib import Path

from super_harness.model import Folder
from super_harness.store import storegit
from super_harness.store.paths import ProjectPaths, StorePaths

_PACKAGE_DEFAULTS = resources.files("super_harness.store") / "defaults"


def _seed(name: str, target: Path) -> None:
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((_PACKAGE_DEFAULTS / name).read_text(encoding="utf-8"), encoding="utf-8")


def ensure_store(paths: StorePaths) -> None:
    """Create the store layout and its git repo; existing files are never touched."""
    for directory in (paths.memory, paths.defaults, paths.projects, paths.journal, paths.locks):
        directory.mkdir(parents=True, exist_ok=True)
    paths.home.chmod(0o700)
    _seed("MEMORY.md", paths.memory / "MEMORY.md")
    _seed("DECISIONS.md", paths.memory / "DECISIONS.md")
    _seed("SETTINGS.md", paths.defaults / "SETTINGS.md")
    _seed("PROCESS.md", paths.defaults / "PROCESS.md")
    storegit.ensure_repo(paths.home)


def ensure_project(paths: StorePaths, slug: str) -> ProjectPaths:
    """Create a project's folders and memory link; copy SETTINGS.md and PROCESS.md if missing."""
    project = paths.project(slug)
    project.plans.mkdir(parents=True, exist_ok=True)
    for folder in Folder:
        project.folder(folder).mkdir(parents=True, exist_ok=True)
    if not project.memory_link.is_symlink():
        project.memory_link.symlink_to(Path("..") / ".." / "memory", target_is_directory=True)
    for target in (project.settings, project.process):
        if not target.exists():
            source = paths.defaults / target.name
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return project
```

```python title="src/super_harness/store/__init__.py"
"""The ~/.harness store: paths, files, documents, registry, links and its git history."""

from super_harness.store.paths import ProjectPaths, StorePaths, harness_home

__all__ = ["ProjectPaths", "StorePaths", "harness_home"]
```

- [ ] **Step 5: Write the seed files** (copied once into a new store; SETTINGS.md is system spec §4.6 verbatim)

````markdown title="src/super_harness/store/defaults/MEMORY.md"
# MEMORY.md

Global memory, read at the start of every command. One fact per line, about 20 words at most. Write with `harness memory add`; lines marked (pin) survive compaction.

## Working style

## Goals

## Preferences

## Turned down
````

````markdown title="src/super_harness/store/defaults/DECISIONS.md"
# DECISIONS.md

Global decision log, newest last. One line each: `- YYYY-MM-DD [project] decision. why: … rejected: …`. Write with `harness memory add --decision`.
````

````markdown title="src/super_harness/store/defaults/PROCESS.md"
# PROCESS.md

How this project builds, tests and ships, for the agents working on it. At most 100 lines; set the commands themselves in SETTINGS.md (`project.test_cmd`, `project.lint_cmd`).

## Process notes
````

````markdown title="src/super_harness/store/defaults/SETTINGS.md"
# SETTINGS.md: harness settings for this project. YAML. Harness never overwrites this file.
version: 1

# project
project.test_cmd: ""          # e.g. "uv run pytest -q"; used by run_tests steps and reviewers
project.lint_cmd: ""

# loops
loop_max.simple: 3
loop_max.standard: 4
loop_max.critical: 6
loop_grant: 2                 # loops added per approval
loop_ask_at_cap: true         # false: park the ticket instead of asking
loop_count_rejected_review: true   # false: plan-review rejections count only toward plan.review_max
stall_repeat: 2               # the same finding fails this many loops in a row → stalled

# planning
grill.round_size: 3
plan.review_max: 2            # 0 = no plan review
plan.reviewer: different-provider   # or provider[/model]

# sessions and limits
sessions.reuse: true          # resume each ticket×role session across loops
sessions.max: 8
sessions.per_provider: {claude: 3, codex: 3, antigravity: 2, gemini: 0}
tokens.per_ticket_max: 250000
step_timeout_min: 30          # a step running longer is killed and retried once
fallback_on_rate_limit: true

# token discipline
skill.max_lines: 80
skill.max_words: 400
memory.compact_at_lines: 200
review.diff_only: true

# agents: role → CLI; an omitted model means the CLI's default model
agents:
  planner:           {on: true,  cli: claude/opus,   skill: plan}
  plan-reviewer:     {on: true,  cli: codex,         skill: review-plan}
  implementer:       {on: true,  cli: codex,         skill: implement, fallback: [claude/sonnet]}
  code-reviewer:     {on: true,  cli: claude/opus,   skill: review-code}
  security-reviewer: {on: true,  cli: claude/sonnet, skill: review-security, blocking: true}
  test-runner:       {on: false, cli: shell,         skill: run-tests}
  doc-writer:        {on: false, cli: antigravity,   skill: sync-docs}

# workflows: steps run in order; on_fail routes a failing verdict back and adds a loop
workflows:
  simple:   {steps: [plan, implement, review_code], on_fail: {review_code: implement}}
  standard: {steps: [plan, review_plan, implement, review_code],
             on_fail: {review_plan: plan, review_code: implement}}
  critical: {steps: [plan, review_plan, implement, review_code, security],
             on_fail: {review_plan: plan, review_code: implement, security: implement}}

# sub-status shown while a step runs
status.names: {plan: under_planning, review_plan: under_plan_review, implement: under_implementation,
               review_code: under_review, security: under_security_review, run_tests: under_test,
               docs: under_docs, approve: needs_approval}

# merge: ask | auto | branch
merge.mode: ask
````

- [ ] **Step 6: Run the tests** — `uv run pytest tests/test_store_basics.py tests/test_frontmatter.py tests/test_documents.py tests/test_links.py` → `27 passed`.

- [ ] **Step 7: Write the module doc**

```markdown title="docs/modules/store/README.md"
# store

## Purpose

Everything under `~/.harness`: paths, atomic writes, frontmatter documents, ids, locks, the registry, `.harness` links, seeding, and the store's own git history.

## Interface

- `StorePaths.default()` and `ProjectPaths`: the layout of system spec §4.1; `HARNESS_HOME` overrides `~/.harness`.
- `seed.ensure_store`, `seed.ensure_project`: create folders and copy default files only when missing.
- `documents`: `load_plan`, `load_ticket`, `load_any`, `save_plan`, `save_ticket` (a ticket lands in the folder its status names), `save_any`, `find_ticket`, `iter_documents`, `check_document`.
- `frontmatter.parse`, `frontmatter.render`, `files.atomic_write`, `ids.new_id`, `locks.locked`, `yamlio.load_yaml`, `yamlio.dump_yaml`.
- `registry`: `load_registry`, `save_registry`, `slugify`, `unique_slug`, `slug_for_path`.
- `links`: `link_state`, `obstruction`, `make_link`, `ensure_excluded`, `is_excluded`.
- `storegit.commit_store`: commits every change as `harness`, never with the user's identity, hooks or signing.

## Invariants

- Only harness writes here; every write is a temp file, fsync and rename inside the real directory.
- A status move renames the file first and then rewrites it, so a crash leaves exactly one copy.
- `runtime/` and `worktrees/` stay out of the store's git.
- A content line that reads as a known `## ` heading is written with an extra leading backslash.

## Changes

- 2026-10-22: store core: layout, atomic files, frontmatter, documents, ids, locks, registry, links, seeding, store git (SP2 M1).
```

- [ ] **Step 8: Lint and commit** — `uv run ruff format . && uv run ruff check . && uv run mypy`, then:

```bash
git add src/super_harness/store tests/conftest.py tests/test_store_basics.py tests/test_frontmatter.py tests/test_documents.py tests/test_links.py docs/modules/store
git commit -m "feat(store): layout, atomic documents, registry, links and store git" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `ops.projects`

**Files:** Create `src/super_harness/ops/__init__.py`, `src/super_harness/ops/projects.py`, `tests/test_ops_projects.py`, `docs/modules/ops/README.md`.

**Interfaces — Consumes:** Tasks 2–3. **Produces:** `InitResult(slug, repo, link_target, created, warnings)`, `Problem(message, slug=None, fixed=False)`, `DoctorReport(projects, problems)`, `AdoptResult(slug, added, conflicts, archive)`; `repo_root(path)`, `init_project(path, paths=None)`, `relink(slug, new_path, paths=None)`, `doctor(fix=False, scan=None, paths=None)`, `adopt(path, paths=None)`.

- [ ] **Step 1: Write the failing test**

```python title="tests/test_ops_projects.py"
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from super_harness.model import Doc, Folder, NeedsSetup, Ticket, UserError
from super_harness.ops import projects
from super_harness.store import StorePaths, documents, links
from super_harness.store.paths import ProjectPaths
from super_harness.store.registry import load_registry

MakeTicket = Callable[..., Doc[Ticket]]
NEWER = datetime(2026, 10, 23, 8, 0, tzinfo=UTC)


def test_init_registers_links_and_seeds(
    store_paths: StorePaths, repo: Path, run_git: Callable[..., str]
) -> None:
    result = projects.init_project(repo)
    project = store_paths.project("payments-api")
    assert (result.slug, result.created, result.warnings) == ("payments-api", True, [])
    assert (repo / ".harness").resolve() == project.root.resolve()
    assert (repo / ".harness" / "SETTINGS.md").is_file()
    assert (repo / ".harness" / "memory" / "MEMORY.md").is_file()
    assert links.is_excluded(repo) is True
    assert load_registry(store_paths).projects["payments-api"].path == repo
    assert "harness: init payments-api" in run_git(store_paths.home, "log", "--format=%s")


def test_init_is_idempotent_and_keeps_edits(store_paths: StorePaths, repo: Path) -> None:
    projects.init_project(repo)
    settings = store_paths.project("payments-api").settings
    settings.write_text("# edited\n", encoding="utf-8")
    again = projects.init_project(repo)
    assert (again.slug, again.created) == ("payments-api", False)
    assert settings.read_text(encoding="utf-8") == "# edited\n"


def test_init_from_a_subfolder_registers_the_repo_root(store_paths: StorePaths, repo: Path) -> None:
    (repo / "src").mkdir()
    assert projects.init_project(repo / "src").repo == repo


def test_init_refuses_a_real_harness_folder(store_paths: StorePaths, repo: Path) -> None:
    (repo / ".harness").mkdir()
    with pytest.raises(NeedsSetup, match="harness adopt"):
        projects.init_project(repo)


def test_plain_folder_is_registered_with_a_warning(store_paths: StorePaths, tmp_path: Path) -> None:
    folder = tmp_path / "notes"
    folder.mkdir()
    result = projects.init_project(folder)
    assert result.warnings == ["not a git repository: ticket worktrees will need git"]


def test_doctor_is_quiet_for_a_healthy_store(store_paths: StorePaths, repo: Path) -> None:
    projects.init_project(repo)
    report = projects.doctor()
    assert (report.projects, report.problems) == (1, [])


def test_doctor_without_a_store_says_so(store_paths: StorePaths) -> None:
    [problem] = projects.doctor().problems
    assert problem.message == f"no store at {store_paths.home}; run: harness init"


def test_moved_repo_is_reported_and_relinked(store_paths: StorePaths, repo: Path) -> None:
    projects.init_project(repo)
    moved = repo.with_name("payments")
    repo.rename(moved)
    [problem] = projects.doctor().problems
    assert problem.message.startswith(f"repo missing at {repo}")
    result = projects.relink("payments-api", moved)
    assert result.repo == moved
    assert projects.doctor().problems == []


def test_relink_needs_a_known_slug(store_paths: StorePaths, repo: Path) -> None:
    with pytest.raises(UserError, match="unknown project: nope"):
        projects.relink("nope", repo)


def test_doctor_fix_repairs_a_broken_link(store_paths: StorePaths, repo: Path) -> None:
    projects.init_project(repo)
    (repo / ".harness").unlink()
    [problem] = projects.doctor().problems
    assert problem.message == "link missing; run: harness doctor --fix"
    [fixed] = projects.doctor(fix=True).problems
    assert (fixed.message, fixed.fixed) == ("link missing; repaired", True)
    assert projects.doctor().problems == []


def test_doctor_reports_invalid_documents(store_paths: StorePaths, repo: Path) -> None:
    projects.init_project(repo)
    bad = store_paths.project("payments-api").folder(Folder.in_queue) / "deadbeef.md"
    bad.write_text("no frontmatter", encoding="utf-8")
    [problem] = projects.doctor().problems
    expected = "projects/payments-api/tasks/in_queue/deadbeef.md: document has no frontmatter"
    assert problem.message == expected


def test_doctor_scan_finds_unmanaged_stores(
    store_paths: StorePaths, repo: Path, tmp_path: Path
) -> None:
    projects.init_project(repo)
    stray = tmp_path / "code" / "legacy-crm" / ".harness"
    stray.mkdir(parents=True)
    messages = [problem.message for problem in projects.doctor(scan=tmp_path / "code").problems]
    found = stray.resolve()
    assert messages == [f"unmanaged store {found}; run: harness adopt {found.parent}"]


def test_adopt_merges_by_uuid_and_archives_everything(
    store_paths: StorePaths, repo: Path, make_ticket: MakeTicket
) -> None:
    projects.init_project(repo)
    project = store_paths.project("payments-api")
    shared = uuid4()
    documents.save_ticket(project, make_ticket("a1111111", uuid=shared, title="older"))
    (repo / ".harness").unlink()
    foreign = ProjectPaths(repo / ".harness")
    documents.save_ticket(
        foreign, make_ticket("a1111111", uuid=shared, title="newer", updated=NEWER)
    )
    documents.save_ticket(foreign, make_ticket("b2222222"))
    (foreign.root / "PROCESS.md").write_text("# foreign process\n", encoding="utf-8")

    result = projects.adopt(repo)

    assert (result.added, result.conflicts) == (1, 1)
    merged = documents.find_ticket(project, "a1111111")
    assert merged is not None
    assert documents.load_ticket(merged).meta.title == "newer"
    assert documents.find_ticket(project, "b2222222") is not None
    assert (result.archive / "replaced" / "a1111111.md").is_file()
    assert (result.archive / "original" / "tasks" / "in_queue" / "b2222222.md").is_file()
    assert project.process.read_text(encoding="utf-8") != "# foreign process\n"
    assert links.link_state(repo, project.root) is links.LinkState.ok


def test_adopting_a_new_project_takes_its_settings(store_paths: StorePaths, repo: Path) -> None:
    (repo / ".harness").mkdir()
    (repo / ".harness" / "SETTINGS.md").write_text("version: 1\n", encoding="utf-8")
    result = projects.adopt(repo)
    assert store_paths.project(result.slug).settings.read_text(encoding="utf-8") == "version: 1\n"
    assert (result.added, result.conflicts) == (0, 0)


def test_adopt_needs_a_real_folder(store_paths: StorePaths, repo: Path) -> None:
    with pytest.raises(UserError, match="nothing to adopt"):
        projects.adopt(repo)
```

- [ ] **Step 2: Run it and watch it fail** — `uv run pytest tests/test_ops_projects.py` → `No module named 'super_harness.ops'`.

- [ ] **Step 3: Write the module**

```python title="src/super_harness/ops/__init__.py"
"""Use cases shared by the CLI and the UI."""
```

```python title="src/super_harness/ops/projects.py"
"""Register, check, re-link and adopt projects (SP2 spec §2, items 5-7)."""

import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from super_harness.model import NeedsSetup, Plan, ProjectEntry, Ticket, UserError, utc_now
from super_harness.store import documents, links, storegit
from super_harness.store.locks import locked
from super_harness.store.paths import ProjectPaths, StorePaths
from super_harness.store.registry import (
    load_registry,
    save_registry,
    slug_for_path,
    slugify,
    unique_slug,
)
from super_harness.store.seed import ensure_project, ensure_store

SCAN_DEPTH = 3
SCAN_SKIP = frozenset({".git", ".venv", "node_modules", "__pycache__", links.LINK})
NOT_GIT = "not a git repository: ticket worktrees will need git"


@dataclass
class InitResult:
    slug: str
    repo: Path
    link_target: Path
    created: bool
    warnings: list[str] = field(default_factory=list)


@dataclass
class Problem:
    message: str
    slug: str | None = None
    fixed: bool = False


@dataclass
class DoctorReport:
    projects: int
    problems: list[Problem]


@dataclass
class AdoptResult:
    slug: str
    added: int
    conflicts: int
    archive: Path


def repo_root(path: Path) -> Path:
    """The git top-level that contains `path`, else `path` itself as an absolute path."""
    if not path.is_dir():
        raise UserError(f"not a folder: {path}")
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    return Path(result.stdout.strip()) if result.returncode == 0 else path.absolute()


def init_project(path: Path, paths: StorePaths | None = None) -> InitResult:
    """Register the project containing `path` and link it to the store (idempotent)."""
    paths = paths or StorePaths.default()
    repo = repo_root(path)
    _refuse_obstruction(repo)
    ensure_store(paths)
    slug, created = _register(paths, repo)
    project = ensure_project(paths, slug)
    warnings = _attach(repo, project)
    storegit.commit_store(paths, f"harness: init {slug}")
    return InitResult(slug, repo, project.root, created, warnings)


def relink(slug: str, new_path: Path, paths: StorePaths | None = None) -> InitResult:
    """Point a moved project's registry entry and `.harness` link at its new place."""
    paths = paths or StorePaths.default()
    repo = repo_root(new_path)
    _refuse_obstruction(repo)
    with locked(paths.locks / "registry.lock"):
        registry = load_registry(paths)
        entry = registry.projects.get(slug)
        if entry is None:
            raise UserError(f"unknown project: {slug}")
        entry.path = repo
        save_registry(paths, registry)
    project = ensure_project(paths, slug)
    warnings = _attach(repo, project)
    storegit.commit_store(paths, f"harness: link {slug}")
    return InitResult(slug, repo, project.root, False, warnings)


def doctor(
    fix: bool = False, scan: Path | None = None, paths: StorePaths | None = None
) -> DoctorReport:
    """Check every project's repo, link, exclude entry and documents."""
    paths = paths or StorePaths.default()
    if not paths.home.is_dir():
        return DoctorReport(0, [Problem(f"no store at {paths.home}; run: harness init")])
    registry = load_registry(paths)
    problems: list[Problem] = []
    for slug, entry in sorted(registry.projects.items()):
        problems += _check_project(paths, slug, entry.path, fix)
    if scan is not None:
        known = {entry.path.resolve() for entry in registry.projects.values()}
        for found in _real_folders(scan.resolve(), SCAN_DEPTH):
            if found.parent not in known:
                problems.append(
                    Problem(f"unmanaged store {found}; run: harness adopt {found.parent}")
                )
    return DoctorReport(len(registry.projects), problems)


def adopt(path: Path, paths: StorePaths | None = None) -> AdoptResult:
    """Merge a project's real `.harness/` folder into the store, archive it, and link."""
    paths = paths or StorePaths.default()
    repo = repo_root(path)
    source = repo / links.LINK
    if links.obstruction(repo) is not links.LinkState.real_dir:
        raise UserError(f"nothing to adopt: {source} is not a real folder")
    ensure_store(paths)
    slug, _ = _register(paths, repo)
    project = paths.project(slug)
    archive = project.archive / f"adopted-{utc_now():%Y%m%dT%H%M%SZ}"
    with locked(paths.locks / f"{slug}.lock"):
        project.root.mkdir(parents=True, exist_ok=True)
        for target in (project.settings, project.process):
            incoming = source / target.name
            if not target.exists() and incoming.is_file():
                shutil.copy2(incoming, target)
        ensure_project(paths, slug)
        added, conflicts = _merge(ProjectPaths(source), project, archive / "replaced")
        archive.mkdir(parents=True, exist_ok=True)
        shutil.move(source, archive / "original")
    _attach(repo, project)
    storegit.commit_store(paths, f"harness: adopt {slug}")
    return AdoptResult(slug, added, conflicts, archive)


def _refuse_obstruction(repo: Path) -> None:
    blocker = links.obstruction(repo)
    if blocker is links.LinkState.real_dir:
        raise NeedsSetup(f"{repo / links.LINK} is a real folder; run: harness adopt {repo}")
    if blocker is links.LinkState.blocked:
        raise UserError(f"{repo / links.LINK} is a file; move it away first")


def _register(paths: StorePaths, repo: Path) -> tuple[str, bool]:
    with locked(paths.locks / "registry.lock"):
        registry = load_registry(paths)
        slug = slug_for_path(registry, repo)
        if slug is not None:
            return slug, False
        slug = unique_slug(slugify(repo.name), registry.projects)
        registry.projects[slug] = ProjectEntry(path=repo, base=_branch(repo), added=date.today())
        save_registry(paths, registry)
        return slug, True


def _branch(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "symbolic-ref", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "main"


def _attach(repo: Path, project: ProjectPaths) -> list[str]:
    if links.link_state(repo, project.root) is not links.LinkState.ok:
        links.make_link(repo, project.root)
    return [] if links.ensure_excluded(repo) else [NOT_GIT]


def _check_project(paths: StorePaths, slug: str, repo: Path, fix: bool) -> list[Problem]:
    if not repo.is_dir():
        return [
            Problem(f"repo missing at {repo}; if it moved: harness link {slug} <new-path>", slug)
        ]
    project = paths.project(slug)
    problems: list[Problem] = []
    state = links.link_state(repo, project.root)
    if state is links.LinkState.real_dir:
        problems.append(
            Problem(f"{repo / links.LINK} is a real folder; run: harness adopt {repo}", slug)
        )
    elif state is links.LinkState.blocked:
        message = f"{repo / links.LINK} is a file; move it away, then: harness doctor --fix"
        problems.append(Problem(message, slug))
    elif state is not links.LinkState.ok:
        if fix:
            links.make_link(repo, project.root)
        problems.append(_fixable(f"link {state.value}", slug, fix))
    if links.is_excluded(repo) is False:
        if fix:
            links.ensure_excluded(repo)
        problems.append(_fixable(".harness missing from .git/info/exclude", slug, fix))
    for path, kind in documents.iter_documents(project):
        problem = documents.check_document(path, kind)
        if problem is not None:
            problems.append(Problem(f"{path.relative_to(paths.home)}: {problem}", slug))
    return problems


def _fixable(message: str, slug: str, fixed: bool) -> Problem:
    hint = "repaired" if fixed else "run: harness doctor --fix"
    return Problem(f"{message}; {hint}", slug, fixed)


def _real_folders(root: Path, depth: int) -> list[Path]:
    """Real `.harness/` folders at most `depth` levels below `root`."""
    found: list[Path] = []
    pending = [(root, 0)]
    while pending:
        directory, level = pending.pop()
        candidate = directory / links.LINK
        if candidate.is_dir() and not candidate.is_symlink():
            found.append(candidate)
        if level == depth:
            continue
        try:
            children = [
                child
                for child in directory.iterdir()
                if child.is_dir() and not child.is_symlink() and child.name not in SCAN_SKIP
            ]
        except OSError:
            continue
        pending += [(child, level + 1) for child in children]
    return sorted(found)


def _valid_documents(
    project: ProjectPaths,
) -> Iterator[tuple[Path, Plan | Ticket, dict[str, str]]]:
    for path, kind in documents.iter_documents(project):
        try:
            meta, sections = documents.load_any(path, kind)
        except (UserError, ValidationError):
            continue
        yield path, meta, sections


def _merge(source: ProjectPaths, project: ProjectPaths, replaced: Path) -> tuple[int, int]:
    """Copy plans and tickets from `source`; on a uuid clash the newer `updated` wins."""
    by_uuid = {meta.uuid: (path, meta) for path, meta, _ in _valid_documents(project)}
    taken_ids = {meta.id: meta.uuid for _, meta in by_uuid.values()}
    added = conflicts = 0
    for _, meta, sections in _valid_documents(source):
        clash = by_uuid.get(meta.uuid)
        if clash is None:
            if taken_ids.get(meta.id, meta.uuid) != meta.uuid:
                conflicts += 1
                continue
            added += 1
        else:
            conflicts += 1
            current_path, current = clash
            if current.updated >= meta.updated:
                continue
            replaced.mkdir(parents=True, exist_ok=True)
            shutil.copy2(current_path, replaced / current_path.name)
            current_path.unlink()
        documents.save_any(project, meta, sections)
    return added, conflicts
```

- [ ] **Step 4: Run the tests** — `uv run pytest tests/test_ops_projects.py` → `15 passed`.

- [ ] **Step 5: Write the module doc**

```markdown title="docs/modules/ops/README.md"
# ops

## Purpose

Use cases shared by the CLI and the UI. Each function takes plain arguments, works through `store` and `model`, and returns a dataclass the caller formats.

## Interface

- `projects.init_project(path)` → `InitResult`: registers the repo containing `path`, seeds its store folder, links `<repo>/.harness`, adds the exclude entry. Idempotent.
- `projects.relink(slug, new_path)` → `InitResult`: re-points a moved project.
- `projects.doctor(fix, scan)` → `DoctorReport`: one `Problem` per repo, link, exclude or document issue; `fix` repairs links and exclude entries only.
- `projects.adopt(path)` → `AdoptResult`: merges a real `.harness/` folder by uuid and archives the original.
- Errors are `model` errors and carry their exit code.

## Invariants

- Registry changes happen under `runtime/locks/registry.lock`; project changes under `runtime/locks/<slug>.lock`.
- Every state change ends with a store commit (`harness: <command> <slug>`).
- Adopt deletes nothing: the original folder and every losing copy end up in `projects/<slug>/archive/adopted-<stamp>/`.
- `ops` never imports `cli` or `ui`.

## Changes

- 2026-10-22: project use cases: init, relink, doctor, adopt (SP2 M1).
```

- [ ] **Step 6: Lint and commit** — `uv run ruff format . && uv run ruff check . && uv run mypy`, then:

```bash
git add src/super_harness/ops tests/test_ops_projects.py docs/modules/ops
git commit -m "feat(ops): init, doctor, link and adopt projects" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: CLI commands

**Files:** Modify `src/super_harness/cli.py`, `docs/modules/cli/README.md`; create `tests/test_cli_projects.py`.

**Interfaces — Consumes:** Task 4 (`super_harness.ops.projects`), `super_harness.model.HarnessError`.

- [ ] **Step 1: Write the failing test**

```python title="tests/test_cli_projects.py"
from pathlib import Path

from typer.testing import CliRunner

from super_harness.cli import app
from super_harness.store import StorePaths

runner = CliRunner()


def test_init_then_doctor(store_paths: StorePaths, repo: Path) -> None:
    target = store_paths.project("payments-api").root
    first = runner.invoke(app, ["init", str(repo)])
    assert (first.exit_code, first.stdout) == (
        0,
        f"initialized payments-api: {repo / '.harness'} -> {target}\n",
    )
    second = runner.invoke(app, ["init", str(repo)])
    assert second.stdout == "ok payments-api: already initialized\n"
    doctor = runner.invoke(app, ["doctor"])
    assert (doctor.exit_code, doctor.stdout) == (0, "ok: 1 project\n")
    assert runner.invoke(app, ["doctor", "--quiet"]).stdout == ""


def test_doctor_exit_code_signals_problems(store_paths: StorePaths, repo: Path) -> None:
    runner.invoke(app, ["init", str(repo)])
    (repo / ".harness").unlink()
    result = runner.invoke(app, ["doctor"])
    assert (result.exit_code, result.stdout) == (
        1,
        "payments-api: link missing; run: harness doctor --fix\n",
    )
    fixed = runner.invoke(app, ["doctor", "--fix"])
    assert (fixed.exit_code, fixed.stdout) == (0, "payments-api: link missing; repaired\n")


def test_errors_go_to_stderr_with_spec_exit_codes(store_paths: StorePaths, repo: Path) -> None:
    (repo / ".harness").mkdir()
    result = runner.invoke(app, ["init", str(repo)])
    assert result.exit_code == 4
    assert result.stderr == f"{repo / '.harness'} is a real folder; run: harness adopt {repo}\n"


def test_link_and_adopt(store_paths: StorePaths, repo: Path, tmp_path: Path) -> None:
    runner.invoke(app, ["init", str(repo)])
    moved = repo.with_name("payments")
    repo.rename(moved)
    linked = runner.invoke(app, ["link", "payments-api", str(moved)])
    target = store_paths.project("payments-api").root
    assert linked.stdout == f"linked payments-api: {moved / '.harness'} -> {target}\n"
    legacy = tmp_path / "legacy"
    (legacy / ".harness").mkdir(parents=True)
    adopted = runner.invoke(app, ["adopt", str(legacy)])
    assert adopted.exit_code == 0
    assert adopted.stdout.startswith("adopted legacy: 0 new, 0 conflicts; original kept in ")


def test_json_output(store_paths: StorePaths, repo: Path) -> None:
    result = runner.invoke(app, ["init", str(repo), "--json"])
    assert '"slug": "payments-api"' in result.stdout
```

- [ ] **Step 2: Run it and watch it fail** — `uv run pytest tests/test_cli_projects.py` → exit code 2, `No such command 'init'`.

- [ ] **Step 3: Replace `src/super_harness/cli.py`**

```python title="src/super_harness/cli.py"
"""Command-line entry point for `harness` (alias `hrn`)."""

import dataclasses
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

import typer

from super_harness import __version__
from super_harness.model import HarnessError
from super_harness.ops import projects

app = typer.Typer(
    name="harness",
    help="Run many projects at once with subscription coding-agent CLIs.",
    no_args_is_help=True,
    add_completion=False,
)

AsJson = Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")]


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"super-harness {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_print_version,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Run many projects at once with subscription coding-agent CLIs."""


@contextmanager
def _errors() -> Iterator[None]:
    """Turn a harness error into one stderr line and the spec's exit code."""
    try:
        yield
    except HarnessError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(error.exit_code) from None


def _emit_json(result: Any) -> None:
    typer.echo(json.dumps(dataclasses.asdict(result), default=str, indent=2))


def _emit_link(verb: str, result: projects.InitResult) -> None:
    typer.echo(f"{verb} {result.slug}: {result.repo / '.harness'} -> {result.link_target}")
    for warning in result.warnings:
        typer.echo(f"warning: {warning}")


@app.command()
def init(
    path: Annotated[
        Path | None, typer.Argument(help="A folder inside the project; default: current folder.")
    ] = None,
    as_json: AsJson = False,
) -> None:
    """Register a project and link its .harness folder to the store."""
    with _errors():
        result = projects.init_project(path or Path.cwd())
    if as_json:
        _emit_json(result)
    elif result.created:
        _emit_link("initialized", result)
    else:
        typer.echo(f"ok {result.slug}: already initialized")
        for warning in result.warnings:
            typer.echo(f"warning: {warning}")


@app.command()
def doctor(
    fix: Annotated[bool, typer.Option("--fix", help="Repair links and exclude entries.")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", help="Print problems only.")] = False,
    scan: Annotated[
        Path | None,
        typer.Option(metavar="DIR", help="Also find unmanaged .harness folders under DIR."),
    ] = None,
    as_json: AsJson = False,
) -> None:
    """Check projects, links and documents; --fix repairs links."""
    with _errors():
        report = projects.doctor(fix=fix, scan=scan)
    if as_json:
        _emit_json(report)
    else:
        for problem in report.problems:
            prefix = f"{problem.slug}: " if problem.slug else ""
            typer.echo(prefix + problem.message)
        if not report.problems and not quiet:
            plural = "" if report.projects == 1 else "s"
            typer.echo(f"ok: {report.projects} project{plural}")
    if any(not problem.fixed for problem in report.problems):
        raise typer.Exit(1)


@app.command()
def link(
    slug: Annotated[str, typer.Argument(help="Project slug from the registry.")],
    new_path: Annotated[Path, typer.Argument(help="Where the project lives now.")],
    as_json: AsJson = False,
) -> None:
    """Point a moved project at the store again."""
    with _errors():
        result = projects.relink(slug, new_path)
    if as_json:
        _emit_json(result)
    else:
        _emit_link("linked", result)


@app.command()
def adopt(
    path: Annotated[Path, typer.Argument(help="Project folder that holds a real .harness/.")],
    as_json: AsJson = False,
) -> None:
    """Move a project's real .harness/ folder into the store and link it."""
    with _errors():
        result = projects.adopt(path)
    if as_json:
        _emit_json(result)
    else:
        typer.echo(
            f"adopted {result.slug}: {result.added} new, {result.conflicts} conflicts; "
            f"original kept in {result.archive}"
        )
```

- [ ] **Step 4: Run the tests** — `uv run pytest tests/test_cli.py tests/test_cli_projects.py` → `9 passed`.

- [ ] **Step 5: Update `docs/modules/cli/README.md`** — Interface gains: "`harness init [PATH]`, `doctor [--fix] [--quiet] [--scan DIR]`, `link SLUG NEW_PATH`, `adopt PATH`, each with `--json` (SP2 spec §3)"; Changes gains, on top: "- 2026-10-22: `init`, `doctor`, `link`, `adopt` commands; errors print one stderr line with the spec exit code (SP2 M1)."

- [ ] **Step 6: Lint and commit** — `uv run ruff format . && uv run ruff check . && uv run mypy`, then:

```bash
git add src/super_harness/cli.py tests/test_cli_projects.py docs/modules/cli
git commit -m "feat(cli): init, doctor, link and adopt commands" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Import contracts and status docs

**Files:** Modify `pyproject.toml`, `Makefile`, `docs/architecture.md`, `AGENTS.md`.

- [ ] **Step 1: Add the contracts to `pyproject.toml`**

```toml
[tool.importlinter]
root_package = "super_harness"

[[tool.importlinter.contracts]]
name = "Layers: cli > ops > store > model"
type = "layers"
layers = [
    "super_harness.cli",
    "super_harness.ops",
    "super_harness.store",
    "super_harness.model",
]

[[tool.importlinter.contracts]]
name = "cli reaches the store only through ops"
type = "forbidden"
source_modules = ["super_harness.cli"]
forbidden_modules = ["super_harness.store"]
```

- [ ] **Step 2: Run the contracts quietly in `make lint`** — append this recipe line (TAB-indented) to the `lint` target:

```make
	out=$$(uv run lint-imports 2>&1) || { echo "$$out"; exit 1; }
```

- [ ] **Step 3: Prove a broken contract fails** — temporarily add `from super_harness.store import StorePaths` to `cli.py`, run `make lint` → it prints the broken contract and exits non-zero; remove the line, `make lint` → silent.

- [ ] **Step 4: Update status docs** — `docs/architecture.md`: Status of `model`, `store`, `ops` → "built: M1 (store core)"; `cli` → "`--version`, `init`, `doctor`, `link`, `adopt`"; Sub-projects row 2 → "in progress: M1 store core done". `AGENTS.md` status line → "Status: sub-project 2 of 5 (Store + `harness` CLI), M1 done: `harness init|doctor|link|adopt` work; `docs/architecture.md` tracks what is built."

- [ ] **Step 5: Full check and commit** — `make check` → exit 0, then:

```bash
git add pyproject.toml Makefile docs/architecture.md AGENTS.md
git commit -m "build: enforce module layers with import-linter" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
