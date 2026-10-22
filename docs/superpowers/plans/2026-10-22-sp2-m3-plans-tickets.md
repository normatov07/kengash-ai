# SP2 M3: Plans and Tickets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every code block's `title` names the file it becomes.

**Goal:** A prompt becomes a plan, an approved plan becomes validated tickets, and ticket moves keep folders, statuses and dependencies consistent, all through `harness plan`, `harness ticket` and `harness status`.

**Architecture:** `model` gains `TicketInput`, `SUB_STATUSES` and a one-line `Title`; `store` gains `frontmatter.read_sections` and YAML-safe ids. Four `ops` modules carry the use cases: `records` (find documents across projects, describe bad input, journal and commit), `plans`, `tickets`, `status`. The CLI only parses arguments and formats the dataclasses `ops` returns.

**Tech Stack:** as M1.

**Specs:** system spec §4.3, §4.4, §6, §6.1, §8.1; SP2 spec §1 M3, §2 items 8, 9, 11 and 13–18 (added by Task 1), §3, §4, §6.

## Global Constraints

- Errors print one line on stderr; exit codes: 0 ok · 1 error · 2 usage · 4 setup needed · 5 a user decision is needed. Every command takes `--json`; status and action commands print at most 5 lines.
- `ops` functions return dataclasses and the CLI formats them; `cli` imports only `ops` and `model`.
- Each state change takes `runtime/locks/<slug>.lock`, writes atomically, appends its journal events, then commits the store as `harness: <command> <ids>`.
- Ids are unique across the whole store and never read as YAML numbers; tickets reference their plan by id and never copy its prompt.
- Plan statuses: `grilling | draft | in_review | approved | ticketed | rejected`. Ticket statuses `<folder>/<sub>`: `in_queue/{ready,blocked,parked}`; `in_process/` a step name from `status.names` or `waiting_slot, waiting_quota, needs_approval, stalled, failed, awaiting_merge`; `done/{merged,branch_ready,closed}`.
- Every commit touching `src/super_harness/<m>` also touches `docs/modules/<m>/README.md`; commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

### Task 1: Spec decisions for M3

**Files:** Modify `docs/superpowers/specs/2026-10-22-sp2-store-cli-design.md`, `docs/superpowers/specs/2026-10-22-super-harness-design.md`.

- [ ] **Step 1: Add SP2 decisions** — append to §2 of the SP2 spec, after item 12:

```markdown
13. **Ids** are unique across the whole store, plans and tickets alike, and never read as YAML numbers (`12345678`, `1234e567` are re-rolled). Commands that take an id search every project; `--project` narrows the search.
14. **Quick plans** take tickets without `plan approve`: the user's check of the ticket list is their approval (system spec §8.1, `to-ticket`). Other plans must be `approved` (or already `ticketed`); otherwise `ticket add` exits 5.
15. **Saving a plan** makes it a draft again and clears its review verdict and skip flag. A `ticketed` plan can no longer be saved or rejected. `plan reject --why` appends a dated line to `## Review log`.
16. **Moves keep the queue consistent:** `in_queue`, `in_queue/ready` and `in_queue/blocked` resolve to ready or blocked from the dependencies; `done` alone means `done/closed`; `in_process` needs every dependency done. After every move or `depends_on` change, each `ready` or `blocked` ticket of the project is re-derived (`parked` is left alone).
17. **`ticket set`** changes `title`, `importance`, `workflow`, `gate`, `loop_max`, `touches`, `depends_on` and `tags`; lists take `[a, b]` or `a,b`. Status changes only through `ticket move`.
18. **Attribution:** commands that change state take `--by NAME` (default `$HARNESS_AGENT`, else `unknown`) and journal it.
```

- [ ] **Step 2: Exit code for unapproved plans** — in the SP2 spec §3 table, the `ticket add` row's exit codes become `0 · 1 invalid batch · 5 plan not approved`.

- [ ] **Step 3: Journal event types** — in system spec §6.1, the types list gains `plan.saved` after `plan.created`, `plan.rejected` after `plan.approved`, and `ticket.updated` after `ticket.moved`.

- [ ] **Step 4: Commit** — `make docs` → silent, then `git add docs/superpowers/specs && git commit -m "docs(spec): SP2 decisions for plans and tickets" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`.

---

### Task 2: `TicketInput`, `SUB_STATUSES`, one-line `Title`

**Files:** Modify `src/super_harness/model/core.py`, `src/super_harness/model/documents.py`, `src/super_harness/model/__init__.py`, `tests/test_model.py`, `docs/modules/model/README.md`.

**Interfaces — Produces:** `Title` (stripped, non-empty, one line), `SUB_STATUSES: dict[Folder, tuple[str, ...]]`, `Ticket.sub_status`, `TicketInput(key, title, importance, gate, touches, depends_on, tags, scope, acceptance)`.

- [ ] **Step 1: Write the failing tests** — in `tests/test_model.py` change the model import to `from super_harness.model import SUB_STATUSES, Folder, Gate, Plan, PlanMode, PlanStatus, Ticket, TicketInput` and append:

```python
def test_titles_are_one_trimmed_line() -> None:
    assert ticket(title="  Rotate keys ").title == "Rotate keys"
    with pytest.raises(ValidationError, match="must be one line"):
        ticket(title="Rotate\nkeys")


def test_sub_status_is_the_part_after_the_folder() -> None:
    item = ticket(status="in_process/needs_approval")
    assert item.sub_status == "needs_approval"
    assert item.sub_status in SUB_STATUSES[Folder.in_process]


def test_ticket_input_defaults_and_unknown_fields() -> None:
    item = TicketInput.model_validate({"title": "Keyring", "importance": "critical"})
    assert (item.key, item.gate, item.depends_on, item.scope) == (None, Gate.afk, [], "")
    with pytest.raises(ValidationError, match="scop"):
        TicketInput.model_validate({"title": "Keyring", "importance": "critical", "scop": "x"})
```

- [ ] **Step 2: Run them and watch them fail** — `uv run pytest tests/test_model.py` → `ImportError: cannot import name 'SUB_STATUSES'`.

- [ ] **Step 3: Add `Title` to `src/super_harness/model/core.py`** — change the pydantic import to `from pydantic import AfterValidator, StringConstraints` and add after `ShortId`:

```python
def _one_line(value: str) -> str:
    if len(value.splitlines()) > 1:
        raise ValueError("must be one line")
    return value


Title = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1), AfterValidator(_one_line)
]
```

- [ ] **Step 4: Extend `src/super_harness/model/documents.py`** — imports become `from typing import Annotated, Literal`, `from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator` and `from super_harness.model.core import Folder, Gate, Importance, ShortId, Title`; `Plan.title` and `Ticket.title` become `title: Title`; add after `_STATUS`:

```python
# in_process also takes the step names of SETTINGS `status.names`.
SUB_STATUSES: dict[Folder, tuple[str, ...]] = {
    Folder.in_queue: ("ready", "blocked", "parked"),
    Folder.in_process: (
        "waiting_slot",
        "waiting_quota",
        "needs_approval",
        "stalled",
        "failed",
        "awaiting_merge",
    ),
    Folder.done: ("merged", "branch_ready", "closed"),
}
```

add to `Ticket`, after `folder`:

```python
    @property
    def sub_status(self) -> str:
        return self.status.split("/", 1)[1]
```

and add after `Ticket`:

```python
class TicketInput(BaseModel):
    """One item of the list `harness ticket add` reads (SP2 spec §4)."""

    model_config = ConfigDict(extra="forbid")

    key: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]+$")] | None = None
    title: Title
    importance: Importance
    gate: Gate = Gate.afk
    touches: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    scope: str = ""
    acceptance: list[str] = Field(default_factory=list)
```

- [ ] **Step 5: Export them** — `src/super_harness/model/__init__.py` imports `SUB_STATUSES` and `TicketInput` from `documents` and `Title` from `core`; add `"SUB_STATUSES"`, `"TicketInput"`, `"Title"` to `__all__`, keeping it sorted.

- [ ] **Step 6: Run the tests** — `uv run pytest tests/test_model.py tests/test_documents.py` → all pass.

- [ ] **Step 7: Update `docs/modules/model/README.md`** — Interface gains "`TicketInput`: one item of `harness ticket add` input (SP2 spec §4); unknown fields are rejected." and "`SUB_STATUSES`: sub-statuses per folder (`in_process` also takes the step names of `status.names`); `Ticket.sub_status`."; the `Importance, Gate, …` line gains `Title`; Invariants gains "Plan and ticket titles are one trimmed, non-empty line."; Changes gains on top "- 2026-10-22: `TicketInput`, `SUB_STATUSES`, one-line `Title`, `Ticket.sub_status` (SP2 M3)."

- [ ] **Step 8: Lint and commit** — `uv run ruff format . && uv run ruff check . && uv run mypy`, then `git add src/super_harness/model tests/test_model.py docs/modules/model && git commit -m "feat(model): ticket input, sub-statuses and one-line titles" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`.

---

### Task 3: Section input and YAML-safe ids in `store`

**Files:** Modify `src/super_harness/store/frontmatter.py`, `src/super_harness/store/ids.py`, `tests/test_frontmatter.py`, `tests/test_store_basics.py`, `docs/modules/store/README.md`.

**Interfaces — Produces:** `frontmatter.read_sections(text, names) -> dict[str, str]`; `ids.new_id` never returns an id YAML reads as a number.

- [ ] **Step 1: Write the failing tests** — in `tests/test_frontmatter.py` change the imports to `from super_harness.model import PLAN_SECTIONS, TICKET_SECTIONS, UserError` and `from super_harness.store.frontmatter import parse, read_sections, render`, then append:

```python
def test_read_sections_takes_known_headings_outside_fences() -> None:
    text = "\n## Goal\nShip it.\n\n## Scope\nKeys only.\n```md\n## Goal\n```\n"
    assert read_sections(text, PLAN_SECTIONS) == {
        "Goal": "Ship it.",
        "Scope": "Keys only.\n```md\n## Goal\n```",
    }


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("## Goals\nx", "unknown section 'Goals'"),
        ("## Goal\nx\n## Goal\ny", "section 'Goal' appears twice"),
        ("intro\n## Goal\nx", "text before the first ## heading"),
    ],
)
def test_read_sections_refuses_bad_input(text: str, message: str) -> None:
    with pytest.raises(UserError, match=message):
        read_sections(text, PLAN_SECTIONS)
```

and append to `tests/test_store_basics.py`:

```python
def test_new_id_skips_ids_that_yaml_reads_as_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    digits = UUID("12345678-0000-4000-8000-000000000000")
    exponent = UUID("1234e567-0000-4000-8000-000000000000")
    free = UUID("a91b3d07-0000-4000-8000-000000000000")
    monkeypatch.setattr("super_harness.store.ids.uuid4", iter([digits, exponent, free]).__next__)
    assert new_id(set()) == ("a91b3d07", free)
```

- [ ] **Step 2: Run them and watch them fail** — `uv run pytest tests/test_frontmatter.py tests/test_store_basics.py` → `cannot import name 'read_sections'`.

- [ ] **Step 3: Add `read_sections`** — in `src/super_harness/store/frontmatter.py`, after `render`:

```python
def read_sections(text: str, names: Sequence[str]) -> dict[str, str]:
    """Parse `## Name` sections typed by an agent; unknown, repeated or stray text is an error.

    Lines inside ``` fences are content, so a Markdown example cannot open a section.
    """
    sections: dict[str, str] = {}
    current: str | None = None
    lines: list[str] = []
    fenced = False
    for line in text.split("\n"):
        if line.startswith("```"):
            fenced = not fenced
        if line.startswith("## ") and not fenced:
            name = line[3:].strip()
            if name not in names:
                known = ", ".join(names)
                raise UserError(f"unknown section {name!r}; use {known} (### for sub-headings)")
            if current is not None:
                sections[current] = "\n".join(lines).strip("\n")
            if name in sections:
                raise UserError(f"section {name!r} appears twice")
            current, lines = name, []
        elif current is not None:
            lines.append(line)
        elif line.strip():
            raise UserError("text before the first ## heading")
    if current is not None:
        sections[current] = "\n".join(lines).strip("\n")
    return sections
```

- [ ] **Step 4: Make ids YAML-safe** — replace `src/super_harness/store/ids.py`:

```python title="src/super_harness/store/ids.py"
"""Plan and ticket ids: uuid4, with its first 8 hex digits as the short id."""

import re
from collections.abc import Container
from uuid import UUID, uuid4

# 12345678 and 1234e567 load from unquoted YAML as numbers, so agents could not list them.
_NUMBER = re.compile(r"[0-9]+(e[0-9]+)?")


def new_id(taken: Container[str]) -> tuple[str, UUID]:
    """Return a fresh (short id, uuid), re-rolling while the short id is taken or numeric."""
    for _ in range(64):
        value = uuid4()
        short = value.hex[:8]
        if short not in taken and not _NUMBER.fullmatch(short):
            return short, value
    raise RuntimeError("no free short id after 64 attempts")
```

- [ ] **Step 5: Run the tests** — `uv run pytest tests/test_frontmatter.py tests/test_store_basics.py` → all pass.

- [ ] **Step 6: Update `docs/modules/store/README.md`** — the `frontmatter.parse, …` Interface line gains `frontmatter.read_sections` (sections typed by an agent: unknown or repeated headings and text before the first heading are refused; ``` fences are respected); Invariants gains "Short ids never read as YAML numbers, so agents can list them unquoted."; Changes gains on top "- 2026-10-22: `read_sections`; ids never read as numbers (SP2 M3)."

- [ ] **Step 7: Lint and commit** — as Task 2, message `feat(store): read typed sections; YAML-safe ids`, paths `src/super_harness/store tests/test_frontmatter.py tests/test_store_basics.py docs/modules/store`.

---

### Task 4: `ops.records` and `ops.plans`

**Files:** Create `src/super_harness/ops/records.py`, `src/super_harness/ops/plans.py`, `tests/test_ops_plans.py`; modify `tests/conftest.py`, `docs/modules/ops/README.md`.

**Interfaces — Consumes:** `workspace.resolve_slug`, `settings.load`, `journal.append`, `storegit.commit_store`, `read_sections`, `new_id`. **Produces:** `records.Document(project, path, meta, sections, text)`, `records.scope`, `locate_plan`, `locate_ticket`, `taken_ids`, `project_tickets`, `load_plan`, `load_ticket`, `document`, `describe`, `one_line`, `record`; `plans.PlanResult(id, project, status, sections, review_skipped)`, `new_plan`, `save_plan`, `show_plan`, `approve_plan`, `reject_plan`; fixtures `registered_repo`, `inside_registered_repo`, `journal_events`.

- [ ] **Step 1: Add shared fixtures** — in `tests/conftest.py` add `import json` and `from super_harness.ops import projects`, then append:

```python
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
```

- [ ] **Step 2: Write the failing test**

```python title="tests/test_ops_plans.py"
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from super_harness.model import NeedsUser, PlanMode, UserError
from super_harness.ops import plans
from super_harness.store import StorePaths

PROMPT = "Make webhook keys rotatable.\n## Goal\nas the user typed it\n"
Events = Callable[[], list[dict[str, Any]]]


def new(repo: Path, mode: PlanMode = PlanMode.direct) -> str:
    return plans.new_plan(
        PROMPT, title="Rotatable keys", mode=mode, project=None, cwd=repo, by="claude"
    ).id


def test_new_plan_keeps_the_prompt_verbatim(
    store_paths: StorePaths,
    registered_repo: Path,
    journal_events: Events,
    run_git: Callable[..., str],
) -> None:
    result = plans.new_plan(
        PROMPT,
        title=" Rotatable keys ",
        mode=PlanMode.grill,
        project=None,
        cwd=registered_repo,
        by="claude",
    )
    assert (result.project, result.status) == ("payments-api", "grilling")
    shown = plans.show_plan(result.id, project=None)
    assert shown.sections["Prompt"] == PROMPT.rstrip("\n")
    assert (shown.meta["title"], shown.meta["review"]["max"]) == ("Rotatable keys", 2)
    assert shown.text.startswith(f"---\nid: {result.id}\n")
    event = journal_events()[-1]
    assert (event["type"], event["plan"], event["mode"], event["by"]) == (
        "plan.created",
        result.id,
        "grill",
        "claude",
    )
    assert f"harness: plan new {result.id}" in run_git(store_paths.home, "log", "--format=%s")


@pytest.mark.parametrize(
    ("prompt", "title", "message"),
    [("  ", "Keys", "the prompt is empty"), ("Rotate.", "Two\nlines", "title: must be one line")],
)
def test_new_plan_refuses_bad_input(
    registered_repo: Path, prompt: str, title: str, message: str
) -> None:
    with pytest.raises(UserError, match=message):
        plans.new_plan(
            prompt, title=title, mode=PlanMode.direct, project=None, cwd=registered_repo, by="x"
        )


def test_new_plan_needs_a_project(registered_repo: Path) -> None:
    with pytest.raises(UserError, match="no project here"):
        plans.new_plan(
            PROMPT,
            title="Keys",
            mode=PlanMode.direct,
            project=None,
            cwd=registered_repo.parent,
            by="x",
        )


def test_save_replaces_sections_and_makes_a_draft(registered_repo: Path) -> None:
    plan_id = new(registered_repo, PlanMode.grill)
    markdown = "## Goal\nShip it.\n\n## Scope\nKeys only.\n"
    result = plans.save_plan(plan_id, markdown, project=None, by="x")
    assert (result.status, result.sections) == ("draft", ["Goal", "Scope"])
    sections = plans.show_plan(plan_id, project=None).sections
    assert (sections["Goal"], sections["Scope"]) == ("Ship it.", "Keys only.")
    assert sections["Prompt"] == PROMPT.rstrip("\n")


@pytest.mark.parametrize(
    ("markdown", "message"),
    [
        ("## Prompt\nnew words", "never changes"),
        ("## Goals\nx", "unknown section 'Goals'"),
        ("\n", "no sections given"),
    ],
)
def test_save_refuses_bad_sections(registered_repo: Path, markdown: str, message: str) -> None:
    plan_id = new(registered_repo)
    with pytest.raises(UserError, match=message):
        plans.save_plan(plan_id, markdown, project=None, by="x")


def test_approval_needs_a_review_or_an_explicit_skip(
    registered_repo: Path, journal_events: Events
) -> None:
    plan_id = new(registered_repo)
    with pytest.raises(NeedsUser, match="--skip-review"):
        plans.approve_plan(plan_id, skip_review=False, project=None, by="x")
    result = plans.approve_plan(plan_id, skip_review=True, project=None, by="x")
    assert (result.status, result.review_skipped) == ("approved", True)
    assert plans.show_plan(plan_id, project=None).meta["review"]["skipped"] is True
    assert journal_events()[-1]["review_skipped"] is True


def test_quick_plans_and_review_max_zero_need_no_skip(
    store_paths: StorePaths, registered_repo: Path
) -> None:
    quick = new(registered_repo, PlanMode.quick)
    assert plans.approve_plan(quick, skip_review=False, project=None, by="x").status == "approved"
    store_paths.project("payments-api").settings.write_text(
        "plan.review_max: 0\n", encoding="utf-8"
    )
    direct = new(registered_repo)
    approved = plans.approve_plan(direct, skip_review=False, project=None, by="x")
    assert (approved.status, approved.review_skipped) == ("approved", False)


def test_only_draft_plans_can_be_approved(registered_repo: Path) -> None:
    plan_id = new(registered_repo, PlanMode.grill)
    with pytest.raises(UserError, match="is grilling"):
        plans.approve_plan(plan_id, skip_review=True, project=None, by="x")


def test_rejection_is_logged_and_saving_revives_the_plan(registered_repo: Path) -> None:
    plan_id = new(registered_repo)
    assert plans.reject_plan(plan_id, "too broad", project=None, by="x").status == "rejected"
    log = plans.show_plan(plan_id, project=None).sections["Review log"]
    assert log.endswith("rejected by the user: too broad")
    assert plans.save_plan(plan_id, "## Goal\nNarrower.", project=None, by="x").status == "draft"


def test_unknown_plans_and_projects(registered_repo: Path) -> None:
    with pytest.raises(UserError, match="unknown plan: deadbeef"):
        plans.show_plan("deadbeef", project=None)
    with pytest.raises(UserError, match="unknown project: nope"):
        plans.show_plan("deadbeef", project="nope")
```

- [ ] **Step 3: Run it and watch it fail** — `uv run pytest tests/test_ops_plans.py` → `cannot import name 'plans'`.

- [ ] **Step 4: Write `records`**

```python title="src/super_harness/ops/records.py"
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
```

- [ ] **Step 5: Write `plans`**

```python title="src/super_harness/ops/plans.py"
"""Plan lifecycle: new, save, show, approve, reject (SP2 spec §2.8, §2.15, §3)."""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from super_harness import settings
from super_harness.model import (
    PLAN_SECTIONS,
    Doc,
    Event,
    NeedsUser,
    Plan,
    PlanMode,
    PlanStatus,
    Review,
    UserError,
    utc_now,
)
from super_harness.ops import records
from super_harness.ops.workspace import resolve_slug
from super_harness.store import documents
from super_harness.store.frontmatter import read_sections
from super_harness.store.ids import new_id
from super_harness.store.locks import locked
from super_harness.store.paths import StorePaths
from super_harness.store.redact import redact


@dataclass
class PlanResult:
    id: str
    project: str
    status: str
    sections: list[str] = field(default_factory=list)
    review_skipped: bool = False


def new_plan(
    prompt: str, *, title: str, mode: PlanMode, project: str | None, cwd: Path, by: str
) -> PlanResult:
    """Keep the user's prompt verbatim in a new plan: `grilling` in grill mode, else `draft`."""
    paths = StorePaths.default()
    slug = resolve_slug(project, cwd, paths)
    if slug is None:
        raise UserError("no project here; pass --project SLUG, or run: harness init")
    if not prompt.strip():
        raise UserError("the prompt is empty")
    review_max = settings.load(paths, slug).plan.review_max
    status = PlanStatus.grilling if mode is PlanMode.grill else PlanStatus.draft
    with locked(paths.locks / f"{slug}.lock"):
        plan_id, uuid = new_id(records.taken_ids(paths))
        now = utc_now()
        try:
            plan = Plan(
                id=plan_id,
                uuid=uuid,
                project=slug,
                title=title,
                mode=mode,
                status=status,
                review=Review(max=review_max),
                created=now,
                updated=now,
            )
        except ValidationError as exc:
            raise UserError(records.describe(exc)) from exc
        documents.save_plan(paths.project(slug), Doc(plan, {"Prompt": prompt}))
    created = Event(
        type="plan.created", project=slug, plan=plan_id, title=plan.title, mode=mode.value, by=by
    )
    records.record(paths, f"harness: plan new {plan_id}", created)
    return PlanResult(plan_id, slug, status.value)


def save_plan(plan_id: str, markdown: str, *, project: str | None, by: str) -> PlanResult:
    """Replace the sections given as `## Name` Markdown; the plan becomes a draft again."""
    sections = read_sections(markdown, PLAN_SECTIONS)
    if not sections:
        raise UserError("no sections given; write each as a ## <Section> heading")
    if "Prompt" in sections:
        raise UserError("the Prompt section holds the user's words and never changes")
    paths = StorePaths.default()
    slug, path = records.locate_plan(paths, plan_id, project)
    with locked(paths.locks / f"{slug}.lock"):
        doc = records.load_plan(path)
        plan = doc.meta
        if plan.status is PlanStatus.ticketed:
            raise UserError(f"plan {plan.id} already has tickets; start a new plan")
        doc.sections.update(sections)
        plan.status = PlanStatus.draft
        plan.review.verdict = None
        plan.review.skipped = False
        plan.updated = utc_now()
        documents.save_plan(paths.project(slug), doc)
    saved = Event(type="plan.saved", project=slug, plan=plan.id, sections=list(sections), by=by)
    records.record(paths, f"harness: plan save {plan.id}", saved)
    return PlanResult(plan.id, slug, plan.status.value, list(sections))


def show_plan(plan_id: str, *, project: str | None) -> records.Document:
    """The plan file, its frontmatter and its sections."""
    paths = StorePaths.default()
    slug, path = records.locate_plan(paths, plan_id, project)
    return records.document(slug, path, records.load_plan(path))


def approve_plan(plan_id: str, *, skip_review: bool, project: str | None, by: str) -> PlanResult:
    """Record the user's approval once the plan is reviewed, quick, or the review is skipped."""
    paths = StorePaths.default()
    slug, path = records.locate_plan(paths, plan_id, project)
    review_max = settings.load(paths, slug).plan.review_max
    with locked(paths.locks / f"{slug}.lock"):
        doc = records.load_plan(path)
        plan = doc.meta
        if plan.status is PlanStatus.approved:
            return PlanResult(plan.id, slug, plan.status.value, review_skipped=plan.review.skipped)
        if plan.status not in (PlanStatus.draft, PlanStatus.in_review):
            raise UserError(
                f"plan {plan.id} is {plan.status.value}; only a draft plan can be approved"
            )
        unreviewed = (
            review_max > 0 and plan.mode is not PlanMode.quick and plan.review.verdict is None
        )
        if unreviewed and not skip_review:
            raise NeedsUser(
                f"plan {plan.id} has no review (plan.review_max: {review_max}); "
                "approve it with --skip-review"
            )
        plan.review.skipped = unreviewed
        plan.status = PlanStatus.approved
        plan.updated = utc_now()
        documents.save_plan(paths.project(slug), doc)
    approved = Event(
        type="plan.approved", project=slug, plan=plan.id, review_skipped=unreviewed, by=by
    )
    records.record(paths, f"harness: plan approve {plan.id}", approved)
    return PlanResult(plan.id, slug, plan.status.value, review_skipped=unreviewed)


def reject_plan(plan_id: str, why: str, *, project: str | None, by: str) -> PlanResult:
    """Record the user's rejection in the Review log; saving the plan again revives it."""
    reason = records.one_line(why, "why")
    paths = StorePaths.default()
    slug, path = records.locate_plan(paths, plan_id, project)
    with locked(paths.locks / f"{slug}.lock"):
        doc = records.load_plan(path)
        plan = doc.meta
        if plan.status is PlanStatus.ticketed:
            raise UserError(f"plan {plan.id} already has tickets; move them instead")
        line = redact(f"- {date.today().isoformat()} rejected by the user: {reason}")
        log = doc.sections.get("Review log", "")
        doc.sections["Review log"] = f"{log}\n{line}" if log else line
        plan.status = PlanStatus.rejected
        plan.updated = utc_now()
        documents.save_plan(paths.project(slug), doc)
    rejected = Event(type="plan.rejected", project=slug, plan=plan.id, why=reason, by=by)
    records.record(paths, f"harness: plan reject {plan.id}", rejected)
    return PlanResult(plan.id, slug, plan.status.value)
```

- [ ] **Step 6: Run the tests** — `uv run pytest tests/test_ops_plans.py` → `13 passed`.

- [ ] **Step 7: Update `docs/modules/ops/README.md`** — Interface gains "`records`: `scope`, `locate_plan`, `locate_ticket` (ids are store-unique; `project` narrows the search), `taken_ids`, `project_tickets`, `load_plan`/`load_ticket` (schema errors become `UserError`), `document` → `Document(project, path, meta, sections, text)`, `describe`, `one_line`, `record` (journal the events, then commit)." and "`plans`: `new_plan`, `save_plan`, `show_plan`, `approve_plan`, `reject_plan` → `PlanResult(id, project, status, sections, review_skipped)`; approval needs a review verdict, a quick plan, `plan.review_max: 0`, or `skip_review`."; Invariants: "Registry changes happen…" line becomes "Registry changes happen under `runtime/locks/registry.lock`; project, plan and ticket changes under `runtime/locks/<slug>.lock`, then journal events, then a store commit."; Changes gains on top "- 2026-10-22: `records` and `plans` (SP2 M3)."

- [ ] **Step 8: Lint and commit** — as Task 2, message `feat(ops): plan lifecycle with store-wide lookups`, paths `src/super_harness/ops tests/test_ops_plans.py tests/conftest.py docs/modules/ops`.

---

### Task 5: `ops.tickets`: add, show, list, find

**Files:** Create `src/super_harness/ops/tickets.py`, `tests/test_ops_tickets.py`; modify `docs/modules/ops/README.md`.

**Interfaces — Consumes:** Task 4's `records` and `plans`; `TicketInput`. **Produces:** `NewTicket(id, key, title, status)`, `Batch(plan, project, tickets)`, `TicketLine(id, project, status, importance, title)`, `add_tickets(plan_id, text, *, project, by) -> Batch`, `show_ticket(ticket_id, *, project) -> records.Document`, `list_tickets(*, project, cwd, folder=None)`, `find_tickets(text, *, project, cwd)`; private `_cycle(graph)`, `_met(depends_on, tickets)` for Task 6.

- [ ] **Step 1: Write the failing test**

```python title="tests/test_ops_tickets.py"
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from super_harness.model import Doc, Folder, NeedsUser, PlanMode, Ticket, UserError
from super_harness.ops import plans, tickets
from super_harness.store import StorePaths, documents

Events = Callable[[], list[dict[str, Any]]]
BATCH = """\
- key: keyring
  title: Keyring with overlap window
  importance: critical
  touches: [services/webhooks]
  tags: [payments]
  scope: Keyring holds current and previous keys.
  acceptance: [Previous key verifies during the overlap window]
- key: rotate
  title: Rotation command
  importance: standard
  depends_on: [keyring]
"""


def plan_for(repo: Path, mode: PlanMode = PlanMode.direct, approve: bool = True) -> str:
    plan_id = plans.new_plan(
        "Rotate keys.", title="Rotatable keys", mode=mode, project=None, cwd=repo, by="x"
    ).id
    if approve:
        plans.approve_plan(plan_id, skip_review=True, project=None, by="x")
    return plan_id


def add(repo: Path, batch: str = BATCH) -> list[str]:
    added = tickets.add_tickets(plan_for(repo), batch, project=None, by="claude")
    return [new.id for new in added.tickets]


def test_add_queues_ready_and_blocked_tickets(
    store_paths: StorePaths, registered_repo: Path, run_git: Callable[..., str]
) -> None:
    plan_id = plan_for(registered_repo)
    keyring, rotate = tickets.add_tickets(plan_id, BATCH, project=None, by="claude").tickets
    assert (keyring.key, keyring.status, rotate.status) == (
        "keyring",
        "in_queue/ready",
        "in_queue/blocked",
    )
    first = tickets.show_ticket(keyring.id, project=None)
    assert (first.meta["workflow"], first.meta["loop_max"], first.meta["touches"]) == (
        "critical",
        6,
        ["services/webhooks"],
    )
    assert first.sections["Scope"] == "Keyring holds current and previous keys."
    assert first.sections["Acceptance"] == "- [ ] Previous key verifies during the overlap window"
    second = tickets.show_ticket(rotate.id, project=None).meta
    assert (second["depends_on"], second["loop_max"], second["plan"]) == ([keyring.id], 4, plan_id)
    plan = plans.show_plan(plan_id, project=None).meta
    assert (plan["status"], plan["tickets"]) == ("ticketed", [keyring.id, rotate.id])
    log = run_git(store_paths.home, "log", "--format=%s")
    assert f"harness: ticket add {keyring.id} {rotate.id}" in log


@pytest.mark.parametrize(
    ("batch", "message"),
    [
        ("{title: x}", "expected a non-empty YAML or JSON list"),
        ("[]", "expected a non-empty"),
        (
            "- {title: x, importance: simple, scop: y}",
            r"ticket 1: scop: unknown field; did you mean scope\?",
        ),
        ("- {title: x, importance: urgent}", "ticket 1: importance: "),
        ("- {title: x, importance: simple, depends_on: [nope]}", "ticket 1: unknown dependency"),
        (
            "- {key: a, title: x, importance: simple}\n- {key: a, title: y, importance: simple}",
            "keys used twice: a",
        ),
        (
            "- {key: a, title: x, importance: simple, depends_on: [b]}\n"
            "- {key: b, title: y, importance: simple, depends_on: [a]}",
            "dependency cycle: a -> b -> a",
        ),
    ],
)
def test_add_refuses_bad_batches(registered_repo: Path, batch: str, message: str) -> None:
    plan_id = plan_for(registered_repo)
    with pytest.raises(UserError, match=message):
        tickets.add_tickets(plan_id, batch, project=None, by="x")


def test_add_needs_an_approved_or_quick_plan(registered_repo: Path) -> None:
    draft = plan_for(registered_repo, approve=False)
    with pytest.raises(NeedsUser, match=f"harness plan approve {draft}"):
        tickets.add_tickets(draft, BATCH, project=None, by="x")
    quick = plan_for(registered_repo, PlanMode.quick, approve=False)
    assert len(tickets.add_tickets(quick, BATCH, project=None, by="x").tickets) == 2


def test_dependencies_on_done_tickets_are_met(
    store_paths: StorePaths, registered_repo: Path, make_ticket: Callable[..., Doc[Ticket]]
) -> None:
    documents.save_ticket(store_paths.project("payments-api"), make_ticket(status="done/merged"))
    batch = "- {title: Follow-up, importance: simple, depends_on: [7b55e0c1]}"
    added = tickets.add_tickets(plan_for(registered_repo), batch, project=None, by="x")
    assert added.tickets[0].status == "in_queue/ready"


def test_list_and_find(registered_repo: Path) -> None:
    keyring, rotate = add(registered_repo)
    lines = tickets.list_tickets(project=None, cwd=registered_repo)
    assert {(line.id, line.status, line.project) for line in lines} == {
        (keyring, "in_queue/ready", "payments-api"),
        (rotate, "in_queue/blocked", "payments-api"),
    }
    assert tickets.list_tickets(project=None, cwd=registered_repo, folder=Folder.done) == []
    assert len(tickets.list_tickets(project=None, cwd=registered_repo.parent)) == 2
    found = tickets.find_tickets("PREVIOUS keys", project=None, cwd=registered_repo)
    assert [line.id for line in found] == [keyring]
```

- [ ] **Step 2: Run it and watch it fail** — `uv run pytest tests/test_ops_tickets.py` → `cannot import name 'tickets'`.

- [ ] **Step 3: Write the module**

```python title="src/super_harness/ops/tickets.py"
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
```

- [ ] **Step 4: Run the tests** — `uv run pytest tests/test_ops_tickets.py` → `11 passed`.

- [ ] **Step 5: Update `docs/modules/ops/README.md`** — Interface gains "`tickets`: `add_tickets` → `Batch(plan, project, tickets=[NewTicket(id, key, title, status)])`, `show_ticket` → `Document`, `list_tickets`/`find_tickets` → `TicketLine(id, project, status, importance, title)`; without a project they cover the project here, else every project."; Invariants gains "`ticket add` validates the whole batch (schema, keys, references, cycles, workflows) before writing any ticket; a ticket is `ready` only when every dependency is done."; Changes gains on top "- 2026-10-22: `tickets` add, show, list, find (SP2 M3)."

- [ ] **Step 6: Lint and commit** — as Task 2, message `feat(ops): add, show, list and find tickets`, paths `src/super_harness/ops tests/test_ops_tickets.py docs/modules/ops`.

---

### Task 6: `ops.tickets`: move and set

**Files:** Modify `src/super_harness/ops/tickets.py`, `tests/test_ops_tickets.py`, `docs/modules/ops/README.md`.

**Interfaces — Consumes:** Task 5's `_cycle`, `_met`. **Produces:** `Moved(id, project, before, after, ready, blocked)`, `Updated(id, project, fields, status)`, `move_ticket(ticket_id, target, why, *, project, by) -> Moved`, `set_fields(ticket_id, pairs, *, project, by) -> Updated`, `SETTABLE`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_ops_tickets.py`:

```python
def test_moving_a_dependency_to_done_unblocks_its_dependents(
    registered_repo: Path, journal_events: Events
) -> None:
    keyring, rotate = add(registered_repo)
    moved = tickets.move_ticket(keyring, "done", "merged by hand", project=None, by="claude")
    assert (moved.before, moved.after, moved.ready) == ("in_queue/ready", "done/closed", [rotate])
    assert tickets.show_ticket(rotate, project=None).meta["status"] == "in_queue/ready"
    back = tickets.move_ticket(keyring, "in_queue", "reopened", project=None, by="claude")
    assert (back.after, back.blocked) == ("in_queue/ready", [rotate])
    moves = [
        (event["ticket"], event["to"], event["by"])
        for event in journal_events()
        if event["type"] == "ticket.moved"
    ]
    assert moves == [
        (keyring, "done/closed", "claude"),
        (rotate, "in_queue/ready", "harness"),
        (keyring, "in_queue/ready", "claude"),
        (rotate, "in_queue/blocked", "harness"),
    ]


@pytest.mark.parametrize(
    ("target", "message"),
    [
        ("nowhere", "unknown folder 'nowhere'"),
        ("in_process", "in_process needs a sub-status"),
        ("in_process/under_the_moon", "in_process has no 'under_the_moon'"),
        ("done/shipped", "done has no 'shipped'"),
    ],
)
def test_move_refuses_unknown_targets(registered_repo: Path, target: str, message: str) -> None:
    keyring, _ = add(registered_repo)
    with pytest.raises(UserError, match=message):
        tickets.move_ticket(keyring, target, "x", project=None, by="x")


def test_blocked_tickets_cannot_start_but_can_park(registered_repo: Path) -> None:
    keyring, rotate = add(registered_repo)
    with pytest.raises(UserError, match=f"{rotate} waits on {keyring}"):
        tickets.move_ticket(rotate, "in_process/under_implementation", "x", project=None, by="x")
    parked = tickets.move_ticket(rotate, "in_queue/parked", "later", project=None, by="x")
    assert parked.after == "in_queue/parked"


def test_set_changes_fields_and_requeues(registered_repo: Path, journal_events: Events) -> None:
    _, rotate = add(registered_repo)
    pairs = ["depends_on=", "tags=api, auth", "loop_max=8"]
    updated = tickets.set_fields(rotate, pairs, project=None, by="claude")
    assert updated.status == "in_queue/ready"
    assert updated.fields == {"depends_on": [], "tags": ["api", "auth"], "loop_max": 8}
    event = journal_events()[-1]
    assert (event["type"], event["fields"]["loop_max"], event["by"]) == (
        "ticket.updated",
        8,
        "claude",
    )


@pytest.mark.parametrize(
    ("pair", "message"),
    [
        ("title", "is not KEY=VALUE"),
        ("status=done/closed", "harness ticket move"),
        ("titel=x", "did you mean title"),
        ("importance=urgent", "importance: "),
        ("workflow=nightly", "no workflow 'nightly'"),
        ("loop_max=0", "cannot go below the current loop"),
        ("depends_on=[deadbeef]", "unknown dependency deadbeef"),
    ],
)
def test_set_refuses_bad_changes(registered_repo: Path, pair: str, message: str) -> None:
    keyring, _ = add(registered_repo)
    with pytest.raises(UserError, match=message):
        tickets.set_fields(keyring, [pair], project=None, by="x")


def test_set_refuses_dependency_cycles(registered_repo: Path) -> None:
    keyring, rotate = add(registered_repo)
    with pytest.raises(UserError, match="dependency cycle"):
        tickets.set_fields(keyring, [f"depends_on={rotate}"], project=None, by="x")
```

- [ ] **Step 2: Run them and watch them fail** — `uv run pytest tests/test_ops_tickets.py` → `AttributeError: module 'super_harness.ops.tickets' has no attribute 'move_ticket'`.

- [ ] **Step 3: Extend the imports of `src/super_harness/ops/tickets.py`** — add `import difflib` above the `collections.abc` import, change `from dataclasses import dataclass` to `from dataclasses import dataclass, field`, add `from typing import Any` after `from pathlib import Path`, add `SUB_STATUSES,` as the first name of the `super_harness.model` import, and change the paths import to `from super_harness.store.paths import ProjectPaths, StorePaths`. Then add after the imports:

```python
SETTABLE = ("title", "importance", "workflow", "gate", "loop_max", "touches", "depends_on", "tags")
LISTS = frozenset({"touches", "depends_on", "tags"})
QUEUED = ("in_queue/ready", "in_queue/blocked")
```

and after `TicketLine`:

```python
@dataclass
class Moved:
    id: str
    project: str
    before: str
    after: str
    ready: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)


@dataclass
class Updated:
    id: str
    project: str
    fields: dict[str, Any]
    status: str
```

- [ ] **Step 4: Add move and set** — after `find_tickets`:

```python
def move_ticket(ticket_id: str, target: str, why: str, *, project: str | None, by: str) -> Moved:
    """Move a ticket to FOLDER[/SUB]; queued tickets then turn ready or blocked to match."""
    reason = records.one_line(why, "why")
    paths = StorePaths.default()
    slug, path = records.locate_ticket(paths, ticket_id, project)
    steps = tuple(settings.load(paths, slug).status.names.values())
    project_paths = paths.project(slug)
    with locked(paths.locks / f"{slug}.lock"):
        doc = records.load_ticket(path)
        tickets = records.project_tickets(paths, slug) | {doc.meta.id: doc}
        ticket = doc.meta
        before, after = ticket.status, _target(target, ticket, tickets, steps)
        if after == before:
            return Moved(ticket.id, slug, before, after)
        ticket.status = after
        ticket.updated = utc_now()
        documents.save_ticket(project_paths, doc)
        ready, blocked = _refresh_queue(project_paths, tickets)
    note = f"{ticket.id} moved to {after}"
    events = [_moved(slug, ticket.id, before, after, reason, by)]
    events += [_moved(slug, tid, QUEUED[1], QUEUED[0], note, "harness") for tid in ready]
    events += [_moved(slug, tid, QUEUED[0], QUEUED[1], note, "harness") for tid in blocked]
    records.record(paths, f"harness: ticket move {ticket.id}", *events)
    return Moved(ticket.id, slug, before, after, ready, blocked)


def set_fields(ticket_id: str, pairs: Sequence[str], *, project: str | None, by: str) -> Updated:
    """Change frontmatter fields from KEY=VALUE pairs; lists take `[a, b]` or `a,b`."""
    changes = _parse_pairs(pairs)
    paths = StorePaths.default()
    slug, path = records.locate_ticket(paths, ticket_id, project)
    workflows = settings.load(paths, slug).workflows
    project_paths = paths.project(slug)
    with locked(paths.locks / f"{slug}.lock"):
        doc = records.load_ticket(path)
        tickets = records.project_tickets(paths, slug) | {doc.meta.id: doc}
        ticket = doc.meta
        try:
            for key, value in changes.items():
                setattr(ticket, key, value)
        except ValidationError as exc:
            raise UserError(records.describe(exc)) from exc
        if "workflow" in changes and ticket.workflow not in workflows:
            raise UserError(f"settings have no workflow {ticket.workflow!r}")
        if ticket.loop_max < ticket.loop:
            raise UserError(f"loop_max cannot go below the current loop ({ticket.loop})")
        if "depends_on" in changes:
            unknown = [dep for dep in ticket.depends_on if dep not in tickets]
            if unknown:
                raise UserError(f"unknown dependency {', '.join(unknown)}")
            cycle = _cycle({tid: item.meta.depends_on for tid, item in tickets.items()})
            if cycle:
                raise UserError(f"dependency cycle: {' -> '.join(cycle)}")
        ticket.updated = utc_now()
        documents.save_ticket(project_paths, doc)
        _refresh_queue(project_paths, tickets)
    values = ticket.model_dump(mode="json")
    fields = {key: values[key] for key in changes}
    updated = Event(
        type="ticket.updated",
        project=slug,
        ticket=ticket.id,
        fields=fields,
        status=ticket.status,
        by=by,
    )
    records.record(paths, f"harness: ticket set {ticket.id}", updated)
    return Updated(ticket.id, slug, fields, ticket.status)
```

and before `_scope_here`:

```python
def _target(
    target: str, ticket: Ticket, tickets: Mapping[str, Doc[Ticket]], steps: Sequence[str]
) -> str:
    """The full status a move to `target` means, once it is allowed."""
    name, _, sub = target.partition("/")
    try:
        folder = Folder(name)
    except ValueError:
        raise UserError(f"unknown folder {name!r}; use in_queue, in_process or done") from None
    met = _met(ticket.depends_on, tickets)
    if folder is Folder.in_queue and sub in ("", "ready", "blocked"):
        sub = "ready" if met else "blocked"
    elif folder is Folder.done and not sub:
        sub = "closed"
    allowed = sorted({*SUB_STATUSES[folder], *(steps if folder is Folder.in_process else ())})
    if sub not in allowed:
        problem = f"has no {sub!r}" if sub else "needs a sub-status"
        raise UserError(f"{folder.value} {problem}; use one of: {', '.join(allowed)}")
    if folder is Folder.in_process and not met:
        waiting = [dep for dep in ticket.depends_on if not _met([dep], tickets)]
        raise UserError(f"{ticket.id} waits on {', '.join(waiting)}")
    return f"{folder.value}/{sub}"


def _refresh_queue(
    project: ProjectPaths, tickets: Mapping[str, Doc[Ticket]]
) -> tuple[list[str], list[str]]:
    """Turn each ready or blocked ticket ready or blocked to match its dependencies."""
    ready: list[str] = []
    blocked: list[str] = []
    for doc in tickets.values():
        ticket = doc.meta
        if ticket.status not in QUEUED:
            continue
        wanted = QUEUED[0] if _met(ticket.depends_on, tickets) else QUEUED[1]
        if wanted != ticket.status:
            ticket.status = wanted
            ticket.updated = utc_now()
            documents.save_ticket(project, doc)
            (ready if wanted == QUEUED[0] else blocked).append(ticket.id)
    return sorted(ready), sorted(blocked)


def _moved(slug: str, ticket_id: str, before: str, after: str, why: str, by: str) -> Event:
    return Event.model_validate(
        {
            "type": "ticket.moved",
            "project": slug,
            "ticket": ticket_id,
            "from": before,
            "to": after,
            "why": why,
            "by": by,
        }
    )


def _parse_pairs(pairs: Sequence[str]) -> dict[str, Any]:
    if not pairs:
        raise UserError("nothing to set; pass KEY=VALUE pairs")
    changes: dict[str, Any] = {}
    for pair in pairs:
        key, sep, raw = pair.partition("=")
        key = key.strip()
        if not sep:
            raise UserError(f"{pair!r} is not KEY=VALUE")
        if key == "status":
            raise UserError("status changes through: harness ticket move ID FOLDER[/SUB] --why W")
        if key not in SETTABLE:
            hint = difflib.get_close_matches(key, SETTABLE, n=1)
            help_text = f"did you mean {hint[0]}?" if hint else f"settable: {', '.join(SETTABLE)}"
            raise UserError(f"cannot set {key!r}; {help_text}")
        changes[key] = _list(raw) if key in LISTS else raw.strip()
    return changes


def _list(raw: str) -> list[Any]:
    text = raw.strip()
    if text.startswith("["):
        value = load_yaml(text, "list")
        if not isinstance(value, list):
            raise UserError(f"{text!r} is not a list")
        return value
    return [part.strip() for part in text.split(",") if part.strip()]
```

- [ ] **Step 5: Run the tests** — `uv run pytest tests/test_ops_tickets.py` → `26 passed`.

- [ ] **Step 6: Update `docs/modules/ops/README.md`** — Interface gains "`tickets.move_ticket` → `Moved(id, project, before, after, ready, blocked)`; `tickets.set_fields` → `Updated(id, project, fields, status)` for the `SETTABLE` fields."; Invariants gains "Queued tickets stay consistent: after any move or `depends_on` change each `ready`/`blocked` ticket is re-derived from its dependencies; `parked` is left alone; `in_process` needs every dependency done."; Changes gains on top "- 2026-10-22: ticket move and set (SP2 M3)."

- [ ] **Step 7: Lint and commit** — as Task 2, message `feat(ops): move and set tickets; keep the queue consistent`, paths `src/super_harness/ops tests/test_ops_tickets.py docs/modules/ops`.

---

### Task 7: `ops.status`

**Files:** Create `src/super_harness/ops/status.py`, `tests/test_ops_status.py`; modify `docs/modules/ops/README.md`.

**Interfaces — Consumes:** `records.scope`, `records.project_tickets`, `workspace.open_gates`. **Produces:** `ProjectStatus(project, folders, statuses, gates)`, `Board(projects)`, `board(project=None) -> Board`.

- [ ] **Step 1: Write the failing test**

```python title="tests/test_ops_status.py"
from collections.abc import Callable
from pathlib import Path

import pytest

from super_harness.model import Doc, Ticket, UserError
from super_harness.ops import status
from super_harness.ops.workspace import OpenGate
from super_harness.store import StorePaths, documents


def test_board_counts_folders_and_lists_gates(
    store_paths: StorePaths, registered_repo: Path, make_ticket: Callable[..., Doc[Ticket]]
) -> None:
    project = store_paths.project("payments-api")
    documents.save_ticket(project, make_ticket(status="in_process/needs_approval"))
    documents.save_ticket(project, make_ticket("a91b3d07", status="in_queue/ready"))
    documents.save_ticket(project, make_ticket("3c9d0e11", status="done/merged"))
    [item] = status.board().projects
    assert item.folders == {"in_queue": 1, "in_process": 1, "done": 1}
    assert item.statuses == {
        "done/merged": 1,
        "in_process/needs_approval": 1,
        "in_queue/ready": 1,
    }
    assert item.gates == [OpenGate("7b55e0c1", "needs_approval", "Rotate keys")]


def test_board_of_an_empty_store(store_paths: StorePaths) -> None:
    assert status.board().projects == []
    with pytest.raises(UserError, match="unknown project: nope"):
        status.board("nope")
```

- [ ] **Step 2: Run it and watch it fail** — `uv run pytest tests/test_ops_status.py` → `cannot import name 'status'`.

- [ ] **Step 3: Write the module**

```python title="src/super_harness/ops/status.py"
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
```

- [ ] **Step 4: Run the tests** — `uv run pytest tests/test_ops_status.py` → `2 passed`.

- [ ] **Step 5: Update `docs/modules/ops/README.md`** — Interface gains "`status.board(project=None)` → `Board([ProjectStatus(project, folders, statuses, gates)])`: every registered project unless one is named."; Changes gains on top "- 2026-10-22: board status (SP2 M3)."

- [ ] **Step 6: Lint and commit** — as Task 2, message `feat(ops): board status per project`, paths `src/super_harness/ops tests/test_ops_status.py docs/modules/ops`.

---

### Task 8: CLI `plan`

**Files:** Modify `src/super_harness/cli.py`, `docs/modules/cli/README.md`; create `tests/test_cli_plans.py`.

- [ ] **Step 1: Write the failing test**

```python title="tests/test_cli_plans.py"
import json
from pathlib import Path

from typer.testing import CliRunner

from super_harness.cli import app

runner = CliRunner()
NEW = ["plan", "new", "--title", "Rotatable keys", "--mode"]


def test_plan_lifecycle(inside_registered_repo: Path) -> None:
    created = runner.invoke(app, [*NEW, "grill"], input="Rotate keys.\n")
    plan_id = created.stdout.split()[1]
    assert created.stdout == f"plan {plan_id} grilling\n"
    saved = runner.invoke(
        app, ["plan", "save", plan_id], input="## Goal\nShip it.\n## Scope\nKeys.\n"
    )
    assert saved.stdout == f"plan {plan_id} draft, 2 sections\n"
    shown = runner.invoke(app, ["plan", "show", plan_id]).stdout
    assert "\n## Prompt\nRotate keys.\n\n## Goal\nShip it.\n" in shown
    unreviewed = runner.invoke(app, ["plan", "approve", plan_id])
    assert unreviewed.exit_code == 5
    assert unreviewed.stderr.endswith("approve it with --skip-review\n")
    approved = runner.invoke(app, ["plan", "approve", plan_id, "--skip-review", "--by", "claude"])
    assert approved.stdout == f"plan {plan_id} approved\n"


def test_plan_json_and_reject(inside_registered_repo: Path) -> None:
    plan_id = runner.invoke(app, [*NEW, "direct"], input="Rotate keys.\n").stdout.split()[1]
    shown = json.loads(runner.invoke(app, ["plan", "show", plan_id, "--json"]).stdout)
    assert (shown["project"], shown["meta"]["status"], shown["sections"]["Prompt"]) == (
        "payments-api",
        "draft",
        "Rotate keys.",
    )
    rejected = runner.invoke(app, ["plan", "reject", plan_id, "--why", "too broad", "--json"])
    assert json.loads(rejected.stdout)["status"] == "rejected"


def test_plan_errors_exit_1(inside_registered_repo: Path) -> None:
    unknown = runner.invoke(app, ["plan", "save", "deadbeef"], input="## Goal\nx\n")
    assert (unknown.exit_code, unknown.stderr) == (1, "unknown plan: deadbeef\n")
    empty = runner.invoke(app, [*NEW, "direct"], input="")
    assert (empty.exit_code, empty.stderr) == (1, "the prompt is empty\n")
```

- [ ] **Step 2: Run it and watch it fail** — `uv run pytest tests/test_cli_plans.py` → exit 2, `No such command 'plan'`.

- [ ] **Step 3: Extend `src/super_harness/cli.py`** — add `import sys` after `import json`; the model import becomes `from super_harness.model import HarnessError, PlanMode, UserError`; the ops import becomes `from super_harness.ops import plans, projects, workspace`. After the `Project` alias add:

```python
Only = Annotated[str | None, typer.Option("--project", "-p", help="Look only in this project.")]
By = Annotated[
    str, typer.Option("--by", envvar="HARNESS_AGENT", help="Who is acting, for the journal.")
]
```

and change `memory_add`'s `by` parameter to `by: By = "unknown",`. Then append:

```python
plan_app = typer.Typer(help="Plans: the user's prompt and the agreed design.", no_args_is_help=True)
app.add_typer(plan_app, name="plan")

PlanId = Annotated[str, typer.Argument(help="Plan id, 8 hex digits.")]


def _stdin(what: str) -> str:
    """Text piped on stdin; an interactive terminal is refused instead of waited on."""
    if sys.stdin.isatty():
        raise UserError(f"pipe the {what} on stdin")
    return sys.stdin.read()


def _emit(result: Any, as_json: bool, line: str) -> None:
    if as_json:
        _emit_json(result)
    else:
        typer.echo(line)


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


@plan_app.command("new")
def plan_new(
    title: Annotated[str, typer.Option("--title", help="One line naming the plan.")],
    mode: Annotated[PlanMode, typer.Option("--mode", help="grill, direct or quick.")],
    project: Project = None,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Start a plan from the user's prompt on stdin, kept verbatim."""
    with _errors():
        result = plans.new_plan(
            _stdin("prompt"), title=title, mode=mode, project=project, cwd=Path.cwd(), by=by
        )
    _emit(result, as_json, f"plan {result.id} {result.status}")


@plan_app.command("save")
def plan_save(
    plan_id: PlanId, project: Only = None, by: By = "unknown", as_json: AsJson = False
) -> None:
    """Replace plan sections with `## Section` Markdown from stdin; the plan becomes a draft."""
    with _errors():
        result = plans.save_plan(plan_id, _stdin("plan sections"), project=project, by=by)
    line = f"plan {result.id} {result.status}, {_plural(len(result.sections), 'section')}"
    _emit(result, as_json, line)


@plan_app.command("show")
def plan_show(plan_id: PlanId, project: Only = None, as_json: AsJson = False) -> None:
    """Print the plan file."""
    with _errors():
        doc = plans.show_plan(plan_id, project=project)
    if as_json:
        _emit_json(doc)
    else:
        typer.echo(doc.text, nl=False)


@plan_app.command("approve")
def plan_approve(
    plan_id: PlanId,
    skip_review: Annotated[
        bool, typer.Option("--skip-review", help="Approve without a plan review.")
    ] = False,
    project: Only = None,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Record the user's approval of a draft plan."""
    with _errors():
        result = plans.approve_plan(plan_id, skip_review=skip_review, project=project, by=by)
    _emit(result, as_json, f"plan {result.id} approved")


@plan_app.command("reject")
def plan_reject(
    plan_id: PlanId,
    why: Annotated[str, typer.Option("--why", help="One line: why the user rejects it.")],
    project: Only = None,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Record the user's rejection of a plan."""
    with _errors():
        result = plans.reject_plan(plan_id, why, project=project, by=by)
    _emit(result, as_json, f"plan {result.id} rejected")
```

- [ ] **Step 4: Run the tests** — `uv run pytest tests/test_cli_plans.py tests/test_cli_workspace.py` → all pass.

- [ ] **Step 5: Update `docs/modules/cli/README.md`** — Interface gains "`harness plan new --title T --mode grill|direct|quick` (prompt on stdin), `plan save ID` (`## Section` Markdown on stdin), `plan show ID`, `plan approve ID [--skip-review]`, `plan reject ID --why W`; id commands take `--project/-p` to narrow the search." and "Commands that change state take `--by NAME` (default `$HARNESS_AGENT`); stdin must be piped, never a terminal."; Changes gains on top "- 2026-10-22: `plan` commands (SP2 M3)."

- [ ] **Step 6: Lint and commit** — as Task 2, message `feat(cli): plan commands`, paths `src/super_harness/cli.py tests/test_cli_plans.py docs/modules/cli`.

---

### Task 9: CLI `ticket` and `status`

**Files:** Modify `src/super_harness/cli.py`, `docs/modules/cli/README.md`; create `tests/test_cli_tickets.py`.

- [ ] **Step 1: Write the failing test**

```python title="tests/test_cli_tickets.py"
import json
from collections.abc import Callable
from pathlib import Path

from typer.testing import CliRunner

from super_harness.cli import app
from super_harness.model import Doc, Ticket
from super_harness.store import StorePaths, documents

runner = CliRunner()
BATCH = """\
- key: keyring
  title: Keyring with overlap window
  importance: critical
- key: rotate
  title: Rotation command
  importance: standard
  depends_on: [keyring]
"""


def approved_plan() -> str:
    new = ["plan", "new", "--title", "Keys", "--mode", "direct"]
    plan_id = runner.invoke(app, new, input="Rotate keys.\n").stdout.split()[1]
    runner.invoke(app, ["plan", "approve", plan_id, "--skip-review"])
    return plan_id


def test_ticket_flow(inside_registered_repo: Path) -> None:
    added = runner.invoke(app, ["ticket", "add", "--plan", approved_plan()], input=BATCH)
    keyring, rotate = added.stdout.split(": ", 1)[1].split(" (")[0].split(", ")
    assert added.stdout == f"2 tickets: {keyring}, {rotate} (1 ready, 1 blocked)\n"
    listed = runner.invoke(app, ["ticket", "list"]).stdout.splitlines()
    assert f"{keyring} in_queue/ready critical payments-api: Keyring with overlap window" in listed
    assert runner.invoke(app, ["ticket", "find", "ROTATION"]).stdout.startswith(f"{rotate} ")
    moved = runner.invoke(app, ["ticket", "move", keyring, "done", "--why", "shipped"])
    assert moved.stdout == f"ticket {keyring} → done/closed\nready: {rotate}\n"
    updated = runner.invoke(app, ["ticket", "set", rotate, "tags=[api]"])
    assert updated.stdout == f"ticket {rotate} updated\n"
    assert "\ntags: [api]\n" in runner.invoke(app, ["ticket", "show", rotate]).stdout
    board = runner.invoke(app, ["status"]).stdout
    assert board == "payments-api: 1 in_queue, 0 in_process, 1 done\n"


def test_ticket_add_reads_a_file_and_speaks_json(
    inside_registered_repo: Path, tmp_path: Path
) -> None:
    plan_id = approved_plan()
    batch = tmp_path / "tickets.json"
    batch.write_text(json.dumps([{"title": "Docs", "importance": "simple"}]), encoding="utf-8")
    added = runner.invoke(app, ["ticket", "add", "--plan", plan_id, "--file", str(batch), "--json"])
    data = json.loads(added.stdout)
    assert (data["plan"], data["tickets"][0]["status"]) == (plan_id, "in_queue/ready")
    listed = json.loads(runner.invoke(app, ["ticket", "list", "--json"]).stdout)
    assert [item["title"] for item in listed] == ["Docs"]


def test_a_bad_batch_exits_1_with_one_line(inside_registered_repo: Path) -> None:
    batch = "- {title: x, importance: simple, scop: y}\n"
    result = runner.invoke(app, ["ticket", "add", "--plan", approved_plan()], input=batch)
    assert (result.exit_code, result.stderr) == (
        1,
        "ticket 1: scop: unknown field; did you mean scope?\n",
    )


def test_status_prints_at_most_five_lines(
    store_paths: StorePaths,
    inside_registered_repo: Path,
    make_ticket: Callable[..., Doc[Ticket]],
) -> None:
    project = store_paths.project("payments-api")
    for n in range(6):
        documents.save_ticket(project, make_ticket(f"aaaaaaa{n}", status="in_process/stalled"))
    lines = runner.invoke(app, ["status"]).stdout.splitlines()
    assert lines[:2] == [
        "payments-api: 0 in_queue, 6 in_process, 0 done",
        "- aaaaaaa0 stalled: Rotate keys (payments-api)",
    ]
    assert (len(lines), lines[-1]) == (5, "+3 more; run: harness status --json")
```

- [ ] **Step 2: Run it and watch it fail** — `uv run pytest tests/test_cli_tickets.py` → exit 2, `No such command 'ticket'`.

- [ ] **Step 3: Extend `src/super_harness/cli.py`** — the model import becomes `from super_harness.model import Folder, HarnessError, PlanMode, UserError`; the ops import becomes `from super_harness.ops import plans, projects, status, tickets, workspace`. Append:

```python
ticket_app = typer.Typer(help="Tickets: one vertical slice of a plan each.", no_args_is_help=True)
app.add_typer(ticket_app, name="ticket")

TicketId = Annotated[str, typer.Argument(help="Ticket id, 8 hex digits.")]
Here = Annotated[
    str | None,
    typer.Option(
        "--project", "-p", help="Project slug; default: the project here, else every project."
    ),
]
MAX_LINES = 5


def _ticket_lines(lines: list[tickets.TicketLine], as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps([dataclasses.asdict(line) for line in lines], indent=2))
        return
    for line in lines:
        typer.echo(f"{line.id} {line.status} {line.importance} {line.project}: {line.title}")


@ticket_app.command("add")
def ticket_add(
    plan: Annotated[str, typer.Option("--plan", help="The plan these tickets slice.")],
    file: Annotated[
        Path | None,
        typer.Option(
            "--file", exists=True, dir_okay=False, help="YAML or JSON list; default: stdin."
        ),
    ] = None,
    project: Only = None,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Add tickets to an approved plan from a YAML or JSON list (SP2 spec §4)."""
    with _errors():
        text = file.read_text(encoding="utf-8") if file else _stdin("ticket list")
        batch = tickets.add_tickets(plan, text, project=project, by=by)
    count = len(batch.tickets)
    ready = sum(new.status == "in_queue/ready" for new in batch.tickets)
    ids = ", ".join(new.id for new in batch.tickets)
    line = f"{_plural(count, 'ticket')}: {ids} ({ready} ready, {count - ready} blocked)"
    _emit(batch, as_json, line)


@ticket_app.command("show")
def ticket_show(ticket_id: TicketId, project: Only = None, as_json: AsJson = False) -> None:
    """Print the ticket file."""
    with _errors():
        doc = tickets.show_ticket(ticket_id, project=project)
    if as_json:
        _emit_json(doc)
    else:
        typer.echo(doc.text, nl=False)


@ticket_app.command("list")
def ticket_list(
    project: Here = None,
    folder: Annotated[Folder | None, typer.Option("--folder", help="Only this folder.")] = None,
    as_json: AsJson = False,
) -> None:
    """One line per ticket: id, status, importance, project and title."""
    with _errors():
        lines = tickets.list_tickets(project=project, cwd=Path.cwd(), folder=folder)
    _ticket_lines(lines, as_json)


@ticket_app.command("find")
def ticket_find(
    text: Annotated[str, typer.Argument(help="Words to look for, in any case.")],
    project: Here = None,
    as_json: AsJson = False,
) -> None:
    """Tickets whose title, tags or text contain TEXT."""
    with _errors():
        lines = tickets.find_tickets(text, project=project, cwd=Path.cwd())
    _ticket_lines(lines, as_json)


@ticket_app.command("set")
def ticket_set(
    ticket_id: TicketId,
    pairs: Annotated[
        list[str], typer.Argument(metavar="KEY=VALUE...", help="e.g. tags=[api,auth] loop_max=8")
    ],
    project: Only = None,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Change title, importance, workflow, gate, loop_max, touches, depends_on or tags."""
    with _errors():
        result = tickets.set_fields(ticket_id, pairs, project=project, by=by)
    _emit(result, as_json, f"ticket {result.id} updated")


@ticket_app.command("move")
def ticket_move(
    ticket_id: TicketId,
    target: Annotated[
        str, typer.Argument(metavar="FOLDER[/SUB]", help="e.g. done or in_queue/parked.")
    ],
    why: Annotated[str, typer.Option("--why", help="One line: why it moves.")],
    project: Only = None,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Move a ticket; queued tickets then turn ready or blocked to match their dependencies."""
    with _errors():
        moved = tickets.move_ticket(ticket_id, target, why, project=project, by=by)
    if as_json:
        _emit_json(moved)
        return
    typer.echo(f"ticket {moved.id} → {moved.after}")
    if moved.ready:
        typer.echo(f"ready: {', '.join(moved.ready)}")
    if moved.blocked:
        typer.echo(f"blocked: {', '.join(moved.blocked)}")


@app.command("status")
def show_status(
    project: Annotated[
        str | None,
        typer.Option("--project", "-p", help="Only this project; default: every project."),
    ] = None,
    as_json: AsJson = False,
) -> None:
    """Board summary: tickets per folder for each project, then gates waiting on the user."""
    with _errors():
        board = status.board(project)
    if as_json:
        _emit_json(board)
        return
    lines = [
        f"{item.project}: {item.folders['in_queue']} in_queue, "
        f"{item.folders['in_process']} in_process, {item.folders['done']} done"
        for item in board.projects
    ]
    lines += [
        f"- {gate.id} {gate.sub_status}: {gate.title} ({item.project})"
        for item in board.projects
        for gate in item.gates
    ]
    if not lines:
        lines = ["no projects; run: harness init"]
    if len(lines) > MAX_LINES:
        more = len(lines) - MAX_LINES + 1
        lines = [*lines[: MAX_LINES - 1], f"+{more} more; run: harness status --json"]
    for line in lines:
        typer.echo(line)
```

- [ ] **Step 4: Run the tests** — `uv run pytest tests/test_cli_tickets.py tests/test_cli_plans.py tests/test_cli_workspace.py tests/test_cli.py tests/test_cli_projects.py` → all pass.

- [ ] **Step 5: Update `docs/modules/cli/README.md`** — Interface gains "`harness ticket add --plan ID [--file F]` (YAML or JSON list, else stdin), `ticket show ID`, `ticket list [--folder F]`, `ticket find TEXT`, `ticket set ID KEY=VALUE…`, `ticket move ID FOLDER[/SUB] --why W`, `status [--project SLUG]`; `list` and `find` cover the project here, else every project; `status` covers every project and prints at most 5 lines."; Changes gains on top "- 2026-10-22: `ticket` and `status` commands (SP2 M3)."

- [ ] **Step 6: Lint and commit** — as Task 2, message `feat(cli): ticket and status commands`, paths `src/super_harness/cli.py tests/test_cli_tickets.py docs/modules/cli`.

---

### Task 10: Status docs and acceptance

**Files:** Modify `docs/architecture.md`, `AGENTS.md`.

- [ ] **Step 1: Update status docs** — `docs/architecture.md`: `cli` Status → "`--version`, `init`, `doctor`, `link`, `adopt`, `settings`, `memory`, `context`, `plan`, `ticket`, `status`"; `ops` Status → "`projects`, `workspace`, `records`, `plans`, `tickets`, `status` (SP2 M1–M3); grows in SP3, SP5"; `model` Status → "Plan, Ticket, TicketInput, Registry, Settings, Event, errors (SP2 M1–M3)"; Sub-projects row 2 → "built: M1 store core, M2 settings, memory, journal, M3 plans and tickets; SP2 review next". `AGENTS.md` status line → "Status: sub-project 2 of 5 (Store + `harness` CLI), M1–M3 built: `harness init|doctor|link|adopt|settings|memory|context|plan|ticket|status` work; SP2 review next. `docs/architecture.md` tracks what is built."

- [ ] **Step 2: Walk the SP2 acceptance list** — in a scratch `HARNESS_HOME` and git repo, run: `harness init`; `echo "Rotate keys." | harness plan new --title Keys --mode direct`; `harness plan approve ID` (exit 5) then `--skip-review`; `harness ticket add --plan ID` with the §4 example plus a dependent ticket; `harness ticket move FIRST done --why x` (the dependent turns ready); `harness ticket move FIRST in_queue --why y` (it turns blocked again); `harness status`; check `journal/*.jsonl` holds `plan.created`, `plan.approved`, `ticket.created`, `ticket.moved`, and the store's `git log` one commit per command.

- [ ] **Step 3: Full check and commit** — `make check` → exit 0, then `git add docs/architecture.md AGENTS.md && git commit -m "docs: SP2 M3 built" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`.
