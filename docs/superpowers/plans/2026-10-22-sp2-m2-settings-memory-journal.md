# SP2 M2: Settings, Memory, Journal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every code block's `title` names the file it becomes.

**Goal:** Agents read resolved settings through `harness settings`, write capped, redacted, journaled facts through `harness memory`, and get their start-of-command digest from `harness context`.

**Architecture:** `model` gains `Settings` and `Event`; `store` gains `redact` and `package_default`; three new units sit between `ops` and `store`: `settings` (layered YAML → validated model), `journal` (append-only JSONL), `memory` (MEMORY.md / DECISIONS.md writes). `ops.workspace` resolves the current project and wraps them for the CLI.

**Tech Stack:** as M1.

**Specs:** system spec §4.5, §4.6, §6.1; SP2 spec §2 items 10–12 and §3 rows `settings`, `memory`, `context`.

## Global Constraints

- Settings resolve package defaults ← `~/.harness/defaults/SETTINGS.md` ← `projects/<slug>/SETTINGS.md`; mappings deep-merge, except each `workflows.<name>` which is replaced whole.
- Dotted keys (`loop_max.simple: 3`) nest; unknown keys fail with "did you mean"; agents never parse SETTINGS.md.
- Memory lines: one line, at most 30 words (aim for 20), redacted, deduplicated; MEMORY.md sections `Working style`, `Goals`, `Preferences`, `Turned down`; DECISIONS.md lines `- YYYY-MM-DD [project] text. why: … rejected: ….`; caps 200 (`memory.compact_at_lines`) and 300.
- Journal: `journal/YYYY-MM-DD.jsonl` (UTC day of `ts`), one JSON object per line, every string redacted before writing, file mode 0600.
- `--project SLUG` defaults to the registered project containing the current folder.
- Import layers: `cli > ops > memory > journal | settings > store > model`; `cli` imports only `ops` and `model`.
- Every commit touching `src/super_harness/<m>` also touches `docs/modules/<m>/README.md`; commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

### Task 1: `Settings` and `Event` schemas

**Files:** Create `src/super_harness/model/settings.py`, `src/super_harness/model/events.py`, `tests/test_model_settings.py`; modify `src/super_harness/model/__init__.py`, `docs/modules/model/README.md`.

**Interfaces — Produces:** `Settings` (fields of system spec §4.6, nested), `Agent`, `Workflow`, `STEP_ROLES: dict[str, str | None]`; `Event(ts, type, project, ticket, plan, **extra)`.

- [ ] **Step 1: Write the failing test**

```python title="tests/test_model_settings.py"
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from super_harness.model import Event, Settings

AGENTS: dict[str, Any] = {
    "planner": {"cli": "claude/opus", "skill": "plan"},
    "implementer": {"cli": "codex", "skill": "implement"},
    "code-reviewer": {"cli": "claude/opus", "skill": "review-code"},
}


def test_defaults_need_no_input() -> None:
    settings = Settings()
    assert (settings.loop_max.critical, settings.merge.mode, settings.sessions.max) == (6, "ask", 8)


def test_workflow_steps_must_be_known() -> None:
    with pytest.raises(ValidationError, match=r"unknown steps \['deploy'\]"):
        Settings.model_validate({"agents": AGENTS, "workflows": {"x": {"steps": ["deploy"]}}})


def test_on_fail_edges_stay_inside_the_workflow() -> None:
    workflow = {"steps": ["plan", "implement"], "on_fail": {"review_code": "implement"}}
    with pytest.raises(ValidationError, match="on_fail edges must join steps"):
        Settings.model_validate({"agents": AGENTS, "workflows": {"x": workflow}})


def test_every_step_needs_its_agent() -> None:
    workflow = {"steps": ["plan", "security"]}
    with pytest.raises(ValidationError, match="security: security-reviewer"):
        Settings.model_validate({"agents": AGENTS, "workflows": {"x": workflow}})


def test_events_keep_extra_fields() -> None:
    event = Event(ts=datetime(2026, 10, 22, tzinfo=UTC), type="step.end", loop=2)
    assert event.model_extra == {"loop": 2}
    assert event.model_dump(mode="json", exclude_none=True) == {
        "ts": "2026-10-22T00:00:00Z",
        "type": "step.end",
        "loop": 2,
    }
```

- [ ] **Step 2: Run it and watch it fail** — `uv run pytest tests/test_model_settings.py` → `ImportError: cannot import name 'Event'`.

- [ ] **Step 3: Write the schemas**

```python title="src/super_harness/model/settings.py"
"""SETTINGS.md schema (system spec §4.6). Unknown keys are rejected."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

STEP_ROLES: dict[str, str | None] = {
    "plan": "planner",
    "review_plan": "plan-reviewer",
    "implement": "implementer",
    "review_code": "code-reviewer",
    "security": "security-reviewer",
    "run_tests": "test-runner",
    "docs": "doc-writer",
    "approve": None,
}


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectCommands(_Section):
    test_cmd: str = ""
    lint_cmd: str = ""


class LoopMax(_Section):
    simple: int = Field(3, ge=1)
    standard: int = Field(4, ge=1)
    critical: int = Field(6, ge=1)


class Grill(_Section):
    round_size: int = Field(3, ge=1, le=4)


class PlanReview(_Section):
    review_max: int = Field(2, ge=0)
    reviewer: str = "different-provider"


def _default_slots() -> dict[str, int]:
    return {"claude": 3, "codex": 3, "antigravity": 2, "gemini": 0}


class Sessions(_Section):
    reuse: bool = True
    max: int = Field(8, ge=1)
    per_provider: dict[str, int] = Field(default_factory=_default_slots)


class Tokens(_Section):
    per_ticket_max: int = Field(250_000, ge=1)


class SkillCaps(_Section):
    max_lines: int = Field(80, ge=1)
    max_words: int = Field(400, ge=1)


class MemoryCaps(_Section):
    compact_at_lines: int = Field(200, ge=10)


class ReviewPolicy(_Section):
    diff_only: bool = True


class Agent(_Section):
    on: bool = True
    cli: str
    skill: str
    blocking: bool = False
    fallback: list[str] = Field(default_factory=list)


class Workflow(_Section):
    steps: list[str] = Field(min_length=1)
    on_fail: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _known_steps(self) -> Self:
        unknown = [step for step in self.steps if step not in STEP_ROLES]
        if unknown:
            raise ValueError(f"unknown steps {unknown}; known: {', '.join(STEP_ROLES)}")
        stray = [
            f"{source}->{target}"
            for source, target in self.on_fail.items()
            if source not in self.steps or target not in self.steps
        ]
        if stray:
            raise ValueError(f"on_fail edges must join steps of this workflow: {', '.join(stray)}")
        return self


class StatusNames(_Section):
    names: dict[str, str] = Field(default_factory=dict)


class Merge(_Section):
    mode: Literal["ask", "auto", "branch"] = "ask"


class Settings(_Section):
    version: Literal[1] = 1
    project: ProjectCommands = Field(default_factory=ProjectCommands)
    loop_max: LoopMax = Field(default_factory=LoopMax)
    loop_grant: int = Field(2, ge=1)
    loop_ask_at_cap: bool = True
    loop_count_rejected_review: bool = True
    stall_repeat: int = Field(2, ge=1)
    grill: Grill = Field(default_factory=Grill)
    plan: PlanReview = Field(default_factory=PlanReview)
    sessions: Sessions = Field(default_factory=Sessions)
    tokens: Tokens = Field(default_factory=Tokens)
    step_timeout_min: int = Field(30, ge=1)
    fallback_on_rate_limit: bool = True
    skill: SkillCaps = Field(default_factory=SkillCaps)
    memory: MemoryCaps = Field(default_factory=MemoryCaps)
    review: ReviewPolicy = Field(default_factory=ReviewPolicy)
    agents: dict[str, Agent] = Field(default_factory=dict)
    workflows: dict[str, Workflow] = Field(default_factory=dict)
    status: StatusNames = Field(default_factory=StatusNames)
    merge: Merge = Field(default_factory=Merge)

    @model_validator(mode="after")
    def _steps_have_agents(self) -> Self:
        missing = sorted(
            {
                f"{step}: {role}"
                for workflow in self.workflows.values()
                for step in workflow.steps
                if (role := STEP_ROLES[step]) is not None and role not in self.agents
            }
        )
        if missing:
            raise ValueError(f"workflow steps need agents: {', '.join(missing)}")
        return self
```

```python title="src/super_harness/model/events.py"
"""Journal events (system spec §6.1): fixed core fields plus any extra detail."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from super_harness.model.core import utc_now


class Event(BaseModel):
    model_config = ConfigDict(extra="allow")

    ts: datetime = Field(default_factory=utc_now)
    type: str
    project: str | None = None
    ticket: str | None = None
    plan: str | None = None
```

- [ ] **Step 4: Export them** — in `src/super_harness/model/__init__.py` add the imports `from super_harness.model.events import Event` and `from super_harness.model.settings import STEP_ROLES, Agent, Settings, Workflow`, and add `"STEP_ROLES"`, `"Agent"`, `"Event"`, `"Settings"`, `"Workflow"` to `__all__` (keep it sorted).

- [ ] **Step 5: Run the tests** — `uv run pytest tests/test_model_settings.py` → `5 passed`.

- [ ] **Step 6: Update `docs/modules/model/README.md`** — Interface gains "`Settings`, `Agent`, `Workflow`, `STEP_ROLES`: the SETTINGS.md schema; workflows may only use known steps whose agents exist." and "`Event`: journal event with core fields `ts`, `type`, `project`, `ticket`, `plan` plus any extra detail."; Changes gains on top "- 2026-10-22: `Settings` and `Event` schemas (SP2 M2)."

- [ ] **Step 7: Lint and commit** — `uv run ruff format . && uv run ruff check . && uv run mypy`, then `git add src/super_harness/model tests/test_model_settings.py docs/modules/model && git commit -m "feat(model): settings and journal event schemas" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`.

---

### Task 2: Redaction and package defaults in `store`

**Files:** Create `src/super_harness/store/redact.py`, `tests/test_redact.py`; modify `src/super_harness/store/seed.py`, `docs/modules/store/README.md`.

**Interfaces — Produces:** `redact(text) -> str`, `MARK = "[REDACTED]"`; `seed.package_default(name) -> str`.

- [ ] **Step 1: Write the failing test**

```python title="tests/test_redact.py"
import pytest

from super_harness.store.redact import MARK, redact


@pytest.mark.parametrize(
    "secret",
    [
        "sk-ant-api03-" + "a" * 24,
        "sk-" + "b" * 32,
        "ghp_" + "c" * 36,
        "github_pat_" + "d" * 40,
        "AKIA" + "E" * 16,
        "xoxb-" + "1" * 24,
    ],
)
def test_tokens_are_redacted(secret: str) -> None:
    assert redact(f"use {secret} now") == f"use {MARK} now"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("password = hunter2", f"password = {MARK}"),
        ("API_KEY: abc123def", f"API_KEY: {MARK}"),
        ("db secret=xyz; next", f"db secret={MARK}; next"),
    ],
)
def test_assignments_keep_the_name(text: str, expected: str) -> None:
    assert redact(text) == expected


def test_private_keys_are_redacted() -> None:
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----"
    assert redact(f"key:\n{pem}\nend") == f"key:\n{MARK}\nend"


def test_ordinary_text_is_untouched() -> None:
    text = "token budget is 250000; skip the secret-santa tokens list"
    assert redact(text) == text
```

- [ ] **Step 2: Run it and watch it fail** — `uv run pytest tests/test_redact.py` → `No module named 'super_harness.store.redact'`.

- [ ] **Step 3: Write the module**

```python title="src/super_harness/store/redact.py"
"""Replace common secrets with [REDACTED] before text reaches the journal or memory."""

import re

MARK = "[REDACTED]"
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S
)
_TOKENS = re.compile(
    r"sk-ant-[A-Za-z0-9_-]{10,}"
    r"|sk-[A-Za-z0-9_-]{20,}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,}"
)
_ASSIGNMENT = re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key)(\s*[:=]\s*)[^\s,;]+")


def redact(text: str) -> str:
    """Return `text` with private keys, API tokens and secret assignments masked."""
    text = _PRIVATE_KEY.sub(MARK, text)
    text = _TOKENS.sub(MARK, text)
    return _ASSIGNMENT.sub(rf"\1\2{MARK}", text)
```

- [ ] **Step 4: Expose package defaults** — in `src/super_harness/store/seed.py` add, after `_PACKAGE_DEFAULTS`:

```python
def package_default(name: str) -> str:
    """Text of a default file shipped inside the package."""
    return (_PACKAGE_DEFAULTS / name).read_text(encoding="utf-8")
```

and make `_seed` write `package_default(name)` instead of reading the resource itself.

- [ ] **Step 5: Run the tests** — `uv run pytest tests/test_redact.py tests/test_ops_projects.py` → all pass (`27 passed`).

- [ ] **Step 6: Update `docs/modules/store/README.md`** — Interface gains "`redact.redact`: masks private keys, API tokens and `password|secret|token|api_key` assignments; applied before anything reaches the journal or memory." and "`seed.package_default(name)`: a default file's text from the package."; Changes gains on top "- 2026-10-22: redaction and `package_default` (SP2 M2)."

- [ ] **Step 7: Lint and commit** — as Task 1, message `feat(store): redact secrets; expose package defaults`, paths `src/super_harness/store tests/test_redact.py docs/modules/store`.

---

### Task 3: `settings` unit

**Files:** Create `src/super_harness/settings.py`, `tests/test_settings.py`, `docs/modules/settings/README.md`.

**Interfaces — Consumes:** `Settings`, `store.seed.package_default`, `store.yamlio.load_yaml`. **Produces:** `unflatten(data) -> dict`, `merge(base, override) -> dict`, `load(paths, slug=None) -> Settings` (raises `UserError` "settings: …"), `problems(paths, slug=None) -> list[str]`, `get(settings, key) -> Any`.

- [ ] **Step 1: Write the failing test**

```python title="tests/test_settings.py"
from pathlib import Path

import pytest

from super_harness import settings
from super_harness.model import UserError
from super_harness.store import StorePaths
from super_harness.store.seed import ensure_project, ensure_store


@pytest.fixture
def project_file(store_paths: StorePaths) -> Path:
    ensure_store(store_paths)
    return ensure_project(store_paths, "app").settings


def test_package_defaults_are_valid(store_paths: StorePaths) -> None:
    resolved = settings.load(store_paths)
    assert (resolved.loop_max.critical, resolved.merge.mode, resolved.grill.round_size) == (
        6,
        "ask",
        3,
    )
    assert resolved.workflows["critical"].steps[-1] == "security"


def test_unflatten_nests_dotted_keys() -> None:
    nested = settings.unflatten({"loop_max.simple": 3, "loop_max": {"critical": 6}})
    assert nested == {"loop_max": {"simple": 3, "critical": 6}}


def test_unflatten_refuses_conflicts() -> None:
    with pytest.raises(UserError, match="conflicts"):
        settings.unflatten({"merge": "ask", "merge.mode": "auto"})


def test_project_file_overrides_defaults(store_paths: StorePaths, project_file: Path) -> None:
    project_file.write_text(
        "loop_max.critical: 8\nagents:\n  implementer: {cli: claude/sonnet}\n", encoding="utf-8"
    )
    resolved = settings.load(store_paths, "app")
    assert (resolved.loop_max.critical, resolved.loop_max.simple) == (8, 3)
    assert resolved.agents["implementer"].cli == "claude/sonnet"
    assert resolved.agents["implementer"].skill == "implement"


def test_a_workflow_override_replaces_the_whole_workflow(
    store_paths: StorePaths, project_file: Path
) -> None:
    project_file.write_text("workflows:\n  simple: {steps: [plan, implement]}\n", encoding="utf-8")
    assert settings.load(store_paths, "app").workflows["simple"].on_fail == {}


def test_unknown_keys_get_a_suggestion(store_paths: StorePaths, project_file: Path) -> None:
    project_file.write_text("loop_max.critcal: 8\n", encoding="utf-8")
    assert settings.problems(store_paths, "app") == [
        "unknown key loop_max.critcal; did you mean loop_max.critical?"
    ]
    with pytest.raises(UserError, match="did you mean loop_max.critical"):
        settings.load(store_paths, "app")


def test_bad_values_name_the_key(store_paths: StorePaths, project_file: Path) -> None:
    project_file.write_text("merge.mode: sometimes\n", encoding="utf-8")
    [problem] = settings.problems(store_paths, "app")
    assert problem.startswith("merge.mode: ")


def test_workflows_must_use_known_steps(store_paths: StorePaths, project_file: Path) -> None:
    project_file.write_text("workflows:\n  simple: {steps: [plan, deploy]}\n", encoding="utf-8")
    [problem] = settings.problems(store_paths, "app")
    assert problem.startswith("workflows.simple: unknown steps ['deploy']")


def test_get_reads_dotted_keys(store_paths: StorePaths) -> None:
    resolved = settings.load(store_paths)
    assert settings.get(resolved, "loop_max.critical") == 6
    assert settings.get(resolved, "agents.planner.cli") == "claude/opus"
    with pytest.raises(UserError, match="did you mean loop_grant"):
        settings.get(resolved, "loop_grnt")
```

- [ ] **Step 2: Run it and watch it fail** — `uv run pytest tests/test_settings.py` → `cannot import name 'settings'`.

- [ ] **Step 3: Write the unit**

```python title="src/super_harness/settings.py"
"""Resolved settings: package defaults, then ~/.harness/defaults, then the project file."""

import difflib
from collections.abc import Mapping
from functools import cache
from typing import Any

from pydantic import ValidationError
from pydantic_core import ErrorDetails

from super_harness.model import Settings, UserError
from super_harness.store.paths import StorePaths
from super_harness.store.seed import package_default
from super_harness.store.yamlio import load_yaml

ATOMIC = frozenset({"workflows"})


def unflatten(data: Mapping[str, Any]) -> dict[str, Any]:
    """Nest dotted keys, recursively: `loop_max.simple: 3` becomes `{loop_max: {simple: 3}}`."""
    out: dict[str, Any] = {}
    for key, raw in data.items():
        value = unflatten(raw) if isinstance(raw, Mapping) else raw
        *parents, leaf = str(key).split(".")
        node = out
        for part in parents:
            child = node.setdefault(part, {})
            if not isinstance(child, dict):
                raise UserError(f"settings: {key} conflicts with {part}")
            node = child
        current = node.get(leaf)
        if isinstance(current, dict) and isinstance(value, dict):
            node[leaf] = merge(current, value)
        elif leaf in node:
            raise UserError(f"settings: {key} conflicts with an earlier key")
        else:
            node[leaf] = value
    return out


def merge(
    base: Mapping[str, Any], override: Mapping[str, Any], path: tuple[str, ...] = ()
) -> dict[str, Any]:
    """Deep-merge `override` onto `base`; each workflow is replaced whole, never mixed."""
    out = dict(base)
    for key, value in override.items():
        current = out.get(key)
        mixable = (
            isinstance(current, Mapping)
            and isinstance(value, Mapping)
            and not (path and path[-1] in ATOMIC)
        )
        out[key] = merge(current, value, (*path, key)) if mixable else value
    return out


def layers(paths: StorePaths, slug: str | None) -> list[dict[str, Any]]:
    """Package defaults, the user's defaults and the project file, in override order."""
    found = [_parse(package_default("SETTINGS.md"), "package SETTINGS.md")]
    files = [(paths.defaults / "SETTINGS.md", "defaults/SETTINGS.md")]
    if slug is not None:
        files.append((paths.project(slug).settings, f"projects/{slug}/SETTINGS.md"))
    for path, source in files:
        if path.is_file():
            found.append(_parse(path.read_text(encoding="utf-8"), source))
    return found


def load(paths: StorePaths, slug: str | None = None) -> Settings:
    """Validated settings for `slug`, or the user's defaults when `slug` is None."""
    try:
        return _resolve(paths, slug)
    except ValidationError as exc:
        found = [_describe(error) for error in exc.errors()]
        more = f" (+{len(found) - 1} more; run: harness settings check)" if len(found) > 1 else ""
        raise UserError(f"settings: {found[0]}{more}") from exc


def problems(paths: StorePaths, slug: str | None = None) -> list[str]:
    """Every problem with the resolved settings; empty when they are valid."""
    try:
        _resolve(paths, slug)
    except UserError as exc:
        return [str(exc)]
    except ValidationError as exc:
        return [_describe(error) for error in exc.errors()]
    return []


def get(resolved: Settings, key: str) -> Any:
    """The value at a dotted key, e.g. `loop_max.critical` or `agents.planner`."""
    data = resolved.model_dump(mode="json")
    node: Any = data
    for part in key.split("."):
        if not isinstance(node, Mapping) or part not in node:
            hint = difflib.get_close_matches(key, _flatten(data), n=1)
            raise UserError(
                f"unknown setting {key}" + (f"; did you mean {hint[0]}?" if hint else "")
            )
        node = node[part]
    return node


def _resolve(paths: StorePaths, slug: str | None) -> Settings:
    resolved: dict[str, Any] = {}
    for layer in layers(paths, slug):
        resolved = merge(resolved, layer)
    return Settings.model_validate(resolved)


def _parse(text: str, source: str) -> dict[str, Any]:
    data = load_yaml(text, source) or {}
    if not isinstance(data, Mapping):
        raise UserError(f"{source}: expected key: value lines")
    return unflatten(data)


def _describe(error: ErrorDetails) -> str:
    key = ".".join(str(part) for part in error["loc"])
    if error["type"] == "extra_forbidden":
        hint = difflib.get_close_matches(key, _known_keys(), n=1)
        return f"unknown key {key}" + (f"; did you mean {hint[0]}?" if hint else "")
    message = error["msg"].removeprefix("Value error, ")
    return f"{key}: {message}" if key else message


@cache
def _known_keys() -> list[str]:
    defaults = _parse(package_default("SETTINGS.md"), "package SETTINGS.md")
    return _flatten(Settings.model_validate(defaults).model_dump(mode="json"))


def _flatten(data: Mapping[str, Any], prefix: str = "") -> list[str]:
    keys: list[str] = []
    for key, value in data.items():
        dotted = f"{prefix}{key}"
        keys.append(dotted)
        if isinstance(value, Mapping):
            keys += _flatten(value, f"{dotted}.")
    return keys
```

- [ ] **Step 4: Run the tests** — `uv run pytest tests/test_settings.py` → `9 passed`.

- [ ] **Step 5: Write the module doc**

```markdown title="docs/modules/settings/README.md"
# settings

## Purpose

Resolve SETTINGS.md into a validated `Settings` model so agents never parse the file themselves.

## Interface

- `load(paths, slug=None)` → `Settings`: package defaults, then `~/.harness/defaults/SETTINGS.md`, then `projects/<slug>/SETTINGS.md`. Raises `UserError("settings: …")` naming the first problem.
- `problems(paths, slug=None)` → one line per problem, empty when valid (`harness settings check`).
- `get(settings, key)` → the value at a dotted key, with a "did you mean" hint for unknown keys.
- `unflatten`, `merge`: the YAML rules below, usable on any mapping.

## Invariants

- Dotted keys nest (`loop_max.simple: 3`); the same key set twice is an error.
- Mappings deep-merge, so a project can override one field of one agent; each `workflows.<name>` is replaced whole, so steps and `on_fail` never mix across files.
- Unknown keys fail with the closest known key as a hint.
- Reading never writes: comment-preserving edits arrive with the UI (SP5).

## Changes

- 2026-10-22: layered load, validation with hints, dotted-key get (SP2 M2).
```

- [ ] **Step 6: Lint and commit** — as Task 1, message `feat(settings): layered, validated settings with hints`, paths `src/super_harness/settings.py tests/test_settings.py docs/modules/settings`.

---

### Task 4: `journal` unit

**Files:** Create `src/super_harness/journal.py`, `tests/test_journal.py`, `docs/modules/journal/README.md`.

**Interfaces — Produces:** `append(paths, event)`, `read(paths, since=None) -> Iterator[Event]`.

- [ ] **Step 1: Write the failing test**

```python title="tests/test_journal.py"
import json
import stat
from datetime import UTC, date, datetime

from super_harness import journal
from super_harness.model import Event
from super_harness.store import StorePaths

TS = datetime(2026, 10, 22, 12, 4, 11, tzinfo=UTC)


def test_events_append_as_redacted_json_lines(store_paths: StorePaths) -> None:
    journal.append(
        store_paths, Event(ts=TS, type="memory.write", project="app", why="token=abc123")
    )
    journal.append(store_paths, Event(ts=TS, type="step.end", ticket="4f2a1b7c", loop=2))
    path = store_paths.journal / "2026-10-22.jsonl"
    first, second = path.read_text(encoding="utf-8").splitlines()
    assert json.loads(first) == {
        "ts": "2026-10-22T12:04:11Z",
        "type": "memory.write",
        "project": "app",
        "why": "token=[REDACTED]",
    }
    assert json.loads(second)["loop"] == 2
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_read_returns_events_in_order_with_extras(store_paths: StorePaths) -> None:
    journal.append(store_paths, Event(ts=TS, type="a"))
    journal.append(store_paths, Event(ts=TS, type="b", files=3))
    events = list(journal.read(store_paths))
    assert [event.type for event in events] == ["a", "b"]
    assert events[1].model_extra == {"files": 3}


def test_read_since_skips_older_days(store_paths: StorePaths) -> None:
    journal.append(store_paths, Event(ts=datetime(2026, 10, 21, tzinfo=UTC), type="old"))
    journal.append(store_paths, Event(ts=TS, type="new"))
    assert [event.type for event in journal.read(store_paths, since=date(2026, 10, 22))] == ["new"]
```

- [ ] **Step 2: Run it and watch it fail** — `uv run pytest tests/test_journal.py` → `cannot import name 'journal'`.

- [ ] **Step 3: Write the unit**

```python title="src/super_harness/journal.py"
"""Append-only JSONL journal, one file per UTC day (system spec §6.1)."""

import json
import os
from collections.abc import Iterator
from datetime import date
from typing import Any

from super_harness.model import Event
from super_harness.store.paths import StorePaths
from super_harness.store.redact import redact


def append(paths: StorePaths, event: Event) -> None:
    """Write one JSON line with every string redacted; O_APPEND keeps concurrent lines whole."""
    data = _scrub(event.model_dump(mode="json", exclude_none=True))
    line = json.dumps(data, ensure_ascii=False) + "\n"
    paths.journal.mkdir(parents=True, exist_ok=True)
    path = paths.journal / f"{event.ts.date().isoformat()}.jsonl"
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def read(paths: StorePaths, since: date | None = None) -> Iterator[Event]:
    """Events in file order, starting at day `since` (inclusive)."""
    for path in sorted(paths.journal.glob("*.jsonl")):
        if since is not None and path.stem < since.isoformat():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                yield Event.model_validate_json(line)


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: _scrub(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value
```

- [ ] **Step 4: Run the tests** — `uv run pytest tests/test_journal.py` → `3 passed`.

- [ ] **Step 5: Write the module doc**

```markdown title="docs/modules/journal/README.md"
# journal

## Purpose

The append-only event log behind monitoring, the UI's live view and the audit trail: who did what, with which model, and why.

## Interface

- `append(paths, event)`: one JSON line in `journal/YYYY-MM-DD.jsonl` (UTC day of `event.ts`).
- `read(paths, since=None)` → `Event`s in file order, from day `since`.

## Invariants

- Lines are never rewritten or deleted.
- Every string is redacted before it is written; files are mode 0600.
- One `os.write` per line with `O_APPEND`, so concurrent writers never interleave inside a line.

## Changes

- 2026-10-22: append and read (SP2 M2).
```

- [ ] **Step 6: Lint and commit** — as Task 1, message `feat(journal): append-only redacted JSONL events`, paths `src/super_harness/journal.py tests/test_journal.py docs/modules/journal`.

---

### Task 5: `memory` unit

**Files:** Create `src/super_harness/memory.py`, `tests/test_memory.py`, `docs/modules/memory/README.md`.

**Interfaces — Consumes:** `journal.append`, `settings.load`, `store`. **Produces:** `SECTIONS`, `AddResult(file, line, lines, cap, added)` with `.over_cap`, `add(paths, text, why, *, section="Preferences", decision=False, rejected=None, project=None, by="unknown")`, `show(paths, *, decisions=False, project=None) -> str`.

- [ ] **Step 1: Write the failing test**

```python title="tests/test_memory.py"
import json
from collections.abc import Callable

import pytest

from super_harness import memory
from super_harness.model import NeedsSetup, UserError
from super_harness.store import StorePaths
from super_harness.store.seed import ensure_store


@pytest.fixture
def store(store_paths: StorePaths) -> StorePaths:
    ensure_store(store_paths)
    return store_paths


def memory_text(store: StorePaths) -> str:
    return (store.memory / "MEMORY.md").read_text(encoding="utf-8")


def test_lines_go_under_their_section(store: StorePaths) -> None:
    memory.add(store, "ships small, reviews hard", "said so", section="Working style")
    memory.add(store, "wants the diff, not prose", "said so", section="Working style")
    expected = (
        "## Working style\n\n- ships small, reviews hard\n- wants the diff, not prose\n\n## Goals"
    )
    assert expected in memory_text(store)


def test_decisions_are_dated_and_tagged(store: StorePaths) -> None:
    result = memory.add(
        store,
        "keyring over single secret",
        "zero-downtime rotation",
        decision=True,
        rejected="one env var",
        project="payments-api",
    )
    assert result.line.startswith("- 20")
    assert result.line.endswith(
        "[payments-api] keyring over single secret. why: zero-downtime rotation. "
        "rejected: one env var."
    )


def test_duplicates_are_not_added_twice(store: StorePaths) -> None:
    assert memory.add(store, "likes tests", "x").added is True
    assert memory.add(store, "likes tests", "x").added is False


@pytest.mark.parametrize(
    ("text", "message"),
    [("two\nlines", "one line"), ("  ", "empty"), ("word " * 31, "under 30 words")],
)
def test_bad_lines_are_refused(store: StorePaths, text: str, message: str) -> None:
    with pytest.raises(UserError, match=message):
        memory.add(store, text, "x")


def test_unknown_sections_are_refused(store: StorePaths) -> None:
    with pytest.raises(UserError, match="unknown section 'Hobbies'"):
        memory.add(store, "x", "y", section="Hobbies")


def test_secrets_never_reach_memory(store: StorePaths) -> None:
    result = memory.add(store, "deploy key is sk-ant-api03-" + "a" * 24, "x")
    assert result.line == "- deploy key is [REDACTED]"
    assert "sk-ant" not in memory_text(store)


def test_writes_are_journaled_and_committed(store: StorePaths, run_git: Callable[..., str]) -> None:
    memory.add(store, "likes tests", "said so", by="claude")
    lines = [
        line for path in store.journal.glob("*.jsonl") for line in path.read_text().splitlines()
    ]
    [event] = [json.loads(line) for line in lines]
    assert (event["type"], event["file"], event["why"], event["by"]) == (
        "memory.write",
        "MEMORY.md",
        "said so",
        "claude",
    )
    assert "harness: memory add MEMORY.md" in run_git(store.home, "log", "--format=%s")


def test_cap_is_reported(store: StorePaths) -> None:
    path = store.memory / "MEMORY.md"
    filler = "".join(f"- fact {n}\n" for n in range(200))
    path.write_text(memory_text(store) + filler, encoding="utf-8")
    result = memory.add(store, "one more", "x")
    assert (result.over_cap, result.cap) == (True, 200)


def test_show_filters_decisions_by_project(store: StorePaths) -> None:
    memory.add(store, "alpha", "x", decision=True, project="one")
    memory.add(store, "beta", "x", decision=True, project="two")
    shown = memory.show(store, decisions=True, project="one")
    assert "[one] alpha." in shown
    assert "[two]" not in shown


def test_memory_needs_a_store(store_paths: StorePaths) -> None:
    with pytest.raises(NeedsSetup, match="harness init"):
        memory.add(store_paths, "x", "y")
```

- [ ] **Step 2: Run it and watch it fail** — `uv run pytest tests/test_memory.py` → `cannot import name 'memory'`.

- [ ] **Step 3: Write the unit**

```python title="src/super_harness/memory.py"
"""MEMORY.md and DECISIONS.md: one-line facts, capped, redacted and journaled (spec §4.5)."""

from dataclasses import dataclass
from datetime import date

from super_harness import journal, settings
from super_harness.model import Event, NeedsSetup, UserError
from super_harness.store import storegit
from super_harness.store.files import atomic_write
from super_harness.store.locks import locked
from super_harness.store.paths import StorePaths
from super_harness.store.redact import redact

SECTIONS = ("Working style", "Goals", "Preferences", "Turned down")
DECISIONS_CAP = 300
MAX_WORDS = 30


@dataclass
class AddResult:
    file: str
    line: str
    lines: int
    cap: int
    added: bool

    @property
    def over_cap(self) -> bool:
        return self.lines > self.cap


def add(
    paths: StorePaths,
    text: str,
    why: str,
    *,
    section: str = "Preferences",
    decision: bool = False,
    rejected: str | None = None,
    project: str | None = None,
    by: str = "unknown",
) -> AddResult:
    """Record one fact in MEMORY.md (under `section`) or one decision in DECISIONS.md."""
    if not paths.memory.is_dir():
        raise NeedsSetup("no store yet; run: harness init")
    fact, reason = _one_line(text), _one_line(why)
    if decision:
        name, cap = "DECISIONS.md", DECISIONS_CAP
        entry = f"- {date.today().isoformat()} [{project or 'global'}] {fact.rstrip('.')}."
        entry += f" why: {reason.rstrip('.')}."
        if rejected:
            entry += f" rejected: {_one_line(rejected).rstrip('.')}."
    else:
        if section not in SECTIONS:
            raise UserError(f"unknown section {section!r}; use one of: {', '.join(SECTIONS)}")
        name, cap = "MEMORY.md", settings.load(paths, project).memory.compact_at_lines
        entry = f"- {fact}"
    entry = redact(entry)
    path = paths.memory / name
    with locked(paths.locks / "memory.lock"):
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        if entry in lines:
            return AddResult(name, entry, len(lines), cap, added=False)
        lines = [*lines, entry] if decision else _insert(lines, section, entry)
        atomic_write(path, "\n".join(lines) + "\n")
    detail = {"type": "memory.write", "project": project, "file": name, "why": reason, "by": by}
    if not decision:
        detail["section"] = section
    journal.append(paths, Event.model_validate(detail))
    storegit.commit_store(paths, f"harness: memory add {name}")
    return AddResult(name, entry, len(lines), cap, added=True)


def show(paths: StorePaths, *, decisions: bool = False, project: str | None = None) -> str:
    """MEMORY.md, or DECISIONS.md filtered to one project's entries when `project` is set."""
    path = paths.memory / ("DECISIONS.md" if decisions else "MEMORY.md")
    if not path.exists():
        raise NeedsSetup("no store yet; run: harness init")
    text = path.read_text(encoding="utf-8")
    if not (decisions and project):
        return text
    tag = f"[{project}]"
    kept = [line for line in text.splitlines() if not line.startswith("- ") or tag in line]
    return "\n".join(kept) + "\n"


def _one_line(text: str) -> str:
    value = text.strip()
    if not value:
        raise UserError("memory text is empty")
    if "\n" in value:
        raise UserError("memory text must be one line")
    if len(value.split()) > MAX_WORDS:
        raise UserError(f"keep memory lines under {MAX_WORDS} words (aim for 20)")
    return value


def _insert(lines: list[str], section: str, entry: str) -> list[str]:
    """Append `entry` to `section`, keeping one blank line after the heading and before the next."""
    heading = f"## {section}"
    if heading not in lines:
        return [*lines, "", heading, "", entry]
    start = lines.index(heading) + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    entries = [line for line in lines[start:end] if line.strip()]
    tail = [""] if end < len(lines) else []
    return [*lines[:start], "", *entries, entry, *tail, *lines[end:]]
```

- [ ] **Step 4: Run the tests** — `uv run pytest tests/test_memory.py` → `12 passed`.

- [ ] **Step 5: Write the module doc**

```markdown title="docs/modules/memory/README.md"
# memory

## Purpose

The agents' long-term memory: MEMORY.md (who the user is, how they work, what they want and have turned down) and DECISIONS.md (what was decided, why, and what was rejected).

## Interface

- `add(paths, text, why, *, section, decision, rejected, project, by)` → `AddResult(file, line, lines, cap, added)`; `.over_cap` when the file passed its cap.
- `show(paths, *, decisions, project)` → MEMORY.md, or DECISIONS.md filtered to one project.
- `SECTIONS`: `Working style`, `Goals`, `Preferences`, `Turned down`.

## Invariants

- One line per fact, at most 30 words; empty or multi-line text is refused.
- Text is redacted before it is written; identical lines are not added twice.
- Every write is journaled (`memory.write` with `file`, `why`, `by`) and committed to the store's git.
- Caps: MEMORY.md `memory.compact_at_lines` (200), DECISIONS.md 300. Passing a cap is reported, not blocked; compaction arrives with the engine (SP3).

## Changes

- 2026-10-22: add and show with caps, redaction, journal and store commits (SP2 M2).
```

- [ ] **Step 6: Lint and commit** — as Task 1, message `feat(memory): capped, redacted, journaled memory and decisions`, paths `src/super_harness/memory.py tests/test_memory.py docs/modules/memory`.

---

### Task 6: `ops.workspace`

**Files:** Create `src/super_harness/ops/workspace.py`, `tests/test_ops_workspace.py`; modify `docs/modules/ops/README.md`.

**Interfaces — Produces:** `resolve_slug(project, cwd, paths=None) -> str | None`, `settings_for(project, cwd)`, `settings_yaml(project, cwd) -> str`, `setting(key, project, cwd)`, `settings_problems(project, cwd) -> list[str]`, `remember(text, why, *, section, decision, rejected, project, cwd, by) -> AddResult`, `recall(decisions, project, cwd) -> str`, `open_gates(paths, slug) -> list[str]`, `context(project, cwd) -> str`.

- [ ] **Step 1: Write the failing test**

```python title="tests/test_ops_workspace.py"
from collections.abc import Callable
from pathlib import Path

import pytest

from super_harness.model import Doc, Ticket, UserError
from super_harness.ops import projects, workspace
from super_harness.store import StorePaths, documents


def test_resolve_slug_from_option_or_folder(store_paths: StorePaths, repo: Path) -> None:
    projects.init_project(repo)
    assert workspace.resolve_slug(None, repo) == "payments-api"
    assert workspace.resolve_slug("payments-api", repo.parent) == "payments-api"
    assert workspace.resolve_slug(None, repo.parent) is None
    with pytest.raises(UserError, match="unknown project: nope"):
        workspace.resolve_slug("nope", repo)


def test_settings_follow_the_current_project(store_paths: StorePaths, repo: Path) -> None:
    projects.init_project(repo)
    store_paths.project("payments-api").settings.write_text(
        "loop_max.critical: 9\n", encoding="utf-8"
    )
    assert workspace.setting("loop_max.critical", None, repo) == 9
    assert workspace.setting("loop_max.critical", None, repo.parent) == 6


def test_context_shows_memory_process_and_gates(
    store_paths: StorePaths, repo: Path, make_ticket: Callable[..., Doc[Ticket]]
) -> None:
    projects.init_project(repo)
    project = store_paths.project("payments-api")
    documents.save_ticket(project, make_ticket(status="in_process/needs_approval"))
    documents.save_ticket(project, make_ticket("a91b3d07", status="in_process/under_review"))
    text = workspace.context(None, repo)
    assert text.startswith("# MEMORY.md")
    assert "# PROCESS.md (payments-api)\n# PROCESS.md\n## Process notes" in text
    assert text.endswith("# Open gates\n- 7b55e0c1 needs_approval: Rotate keys\n")
```

- [ ] **Step 2: Run it and watch it fail** — `uv run pytest tests/test_ops_workspace.py` → `cannot import name 'workspace'`.

- [ ] **Step 3: Write the module**

```python title="src/super_harness/ops/workspace.py"
"""Settings, memory and context for the current project (SP2 spec §3)."""

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from super_harness import memory, settings
from super_harness.model import Folder, NeedsSetup, Settings, UserError
from super_harness.ops.projects import repo_root
from super_harness.store import documents
from super_harness.store.paths import StorePaths
from super_harness.store.registry import load_registry
from super_harness.store.yamlio import dump_yaml

GATES = ("needs_approval", "stalled", "failed", "awaiting_merge")


def resolve_slug(project: str | None, cwd: Path, paths: StorePaths | None = None) -> str | None:
    """The named project, else the registered project containing `cwd`, else None."""
    paths = paths or StorePaths.default()
    registry = load_registry(paths)
    if project is not None:
        if project not in registry.projects:
            raise UserError(f"unknown project: {project}")
        return project
    here = repo_root(cwd)
    for slug, entry in registry.projects.items():
        if here == entry.path or entry.path in here.parents:
            return slug
    return None


def settings_for(project: str | None, cwd: Path) -> Settings:
    paths = StorePaths.default()
    return settings.load(paths, resolve_slug(project, cwd, paths))


def settings_yaml(project: str | None, cwd: Path) -> str:
    return dump_yaml(settings_for(project, cwd).model_dump(mode="json"))


def setting(key: str, project: str | None, cwd: Path) -> Any:
    return settings.get(settings_for(project, cwd), key)


def settings_problems(project: str | None, cwd: Path) -> list[str]:
    paths = StorePaths.default()
    return settings.problems(paths, resolve_slug(project, cwd, paths))


def remember(
    text: str,
    why: str,
    *,
    section: str,
    decision: bool,
    rejected: str | None,
    project: str | None,
    cwd: Path,
    by: str,
) -> memory.AddResult:
    paths = StorePaths.default()
    slug = resolve_slug(project, cwd, paths)
    return memory.add(
        paths, text, why, section=section, decision=decision, rejected=rejected, project=slug, by=by
    )


def recall(decisions: bool, project: str | None, cwd: Path) -> str:
    paths = StorePaths.default()
    return memory.show(paths, decisions=decisions, project=resolve_slug(project, cwd, paths))


def open_gates(paths: StorePaths, slug: str) -> list[str]:
    """In-process tickets waiting for the conductor or the user."""
    gates: list[str] = []
    for path in sorted(paths.project(slug).folder(Folder.in_process).glob("*.md")):
        try:
            ticket = documents.load_ticket(path).meta
        except (UserError, ValidationError):
            continue
        sub_status = ticket.status.split("/", 1)[1]
        if sub_status in GATES:
            gates.append(f"- {ticket.id} {sub_status}: {ticket.title}")
    return gates


def context(project: str | None, cwd: Path) -> str:
    """MEMORY.md, the project's PROCESS.md headings and its open gates."""
    paths = StorePaths.default()
    if not paths.memory.is_dir():
        raise NeedsSetup("no store yet; run: harness init")
    parts = [(paths.memory / "MEMORY.md").read_text(encoding="utf-8").rstrip()]
    slug = resolve_slug(project, cwd, paths)
    if slug is not None:
        process = paths.project(slug).process
        lines = process.read_text(encoding="utf-8").splitlines() if process.exists() else []
        headings = "\n".join(line for line in lines if line.startswith("#")) or "(empty)"
        parts.append(f"# PROCESS.md ({slug})\n{headings}")
        parts.append("# Open gates\n" + ("\n".join(open_gates(paths, slug)) or "none"))
    return "\n\n".join(parts) + "\n"
```

- [ ] **Step 4: Run the tests** — `uv run pytest tests/test_ops_workspace.py` → `3 passed`.

- [ ] **Step 5: Update `docs/modules/ops/README.md`** — Interface gains "`workspace`: `resolve_slug` (named project, else the registered project containing the current folder), settings `settings_yaml`/`setting`/`settings_problems`, memory `remember`/`recall`, `context`, `open_gates`."; Changes gains on top "- 2026-10-22: workspace use cases for settings, memory and context (SP2 M2)."

- [ ] **Step 6: Lint and commit** — as Task 1, message `feat(ops): resolve the current project; settings, memory and context use cases`, paths `src/super_harness/ops tests/test_ops_workspace.py docs/modules/ops`.

---

### Task 7: CLI `settings`, `memory`, `context`

**Files:** Modify `src/super_harness/cli.py`, `docs/modules/cli/README.md`; create `tests/test_cli_workspace.py`.

- [ ] **Step 1: Write the failing test**

```python title="tests/test_cli_workspace.py"
from pathlib import Path

import pytest
from typer.testing import CliRunner

from super_harness.cli import app
from super_harness.store import StorePaths

runner = CliRunner()


@pytest.fixture
def inside_repo(store_paths: StorePaths, repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    runner.invoke(app, ["init", str(repo)])
    monkeypatch.chdir(repo)
    return repo


def test_settings_commands(store_paths: StorePaths, inside_repo: Path) -> None:
    assert runner.invoke(app, ["settings", "get", "loop_max.critical"]).stdout == "6\n"
    planner = runner.invoke(app, ["settings", "get", "agents.planner"]).stdout
    assert planner.startswith('{"on": true, "cli": "claude/opus"')
    assert (
        "loop_max: {simple: 3, standard: 4, critical: 6}\n"
        in runner.invoke(app, ["settings", "show"]).stdout
    )
    check = runner.invoke(app, ["settings", "check"])
    assert (check.exit_code, check.stdout) == (0, "")
    store_paths.project("payments-api").settings.write_text(
        "loop_max.critcal: 1\n", encoding="utf-8"
    )
    bad = runner.invoke(app, ["settings", "check"])
    assert (bad.exit_code, bad.stdout) == (
        1,
        "unknown key loop_max.critcal; did you mean loop_max.critical?\n",
    )


def test_memory_commands_and_context(inside_repo: Path) -> None:
    added = runner.invoke(app, ["memory", "add", "prefers runbooks", "--why", "said so"])
    assert added.stdout == "MEMORY.md +1 line (13/200)\n"
    again = runner.invoke(app, ["memory", "add", "prefers runbooks", "--why", "said so"])
    assert again.stdout == "MEMORY.md: already recorded\n"
    decided = runner.invoke(
        app, ["memory", "add", "keyring over secret", "--why", "rotation", "--decision"]
    )
    assert decided.stdout.startswith("DECISIONS.md +1 line")
    shown = runner.invoke(app, ["memory", "show", "--decisions"]).stdout
    assert "[payments-api] keyring over secret. why: rotation." in shown
    context = runner.invoke(app, ["context"]).stdout
    assert "- prefers runbooks" in context
    assert context.endswith("# Open gates\nnone\n")


def test_memory_errors_exit_1(inside_repo: Path) -> None:
    result = runner.invoke(app, ["memory", "add", "x", "--why", "y", "--section", "Hobbies"])
    assert result.exit_code == 1
    assert result.stderr.startswith("unknown section 'Hobbies'")
```

- [ ] **Step 2: Run it and watch it fail** — `uv run pytest tests/test_cli_workspace.py` → exit 2, `No such command 'settings'`.

- [ ] **Step 3: Extend `src/super_harness/cli.py`** — change the ops import to `from super_harness.ops import projects, workspace`, then append:

```python
settings_app = typer.Typer(
    help="Read resolved settings; agents never parse SETTINGS.md.", no_args_is_help=True
)
memory_app = typer.Typer(help="Global memory and decisions.", no_args_is_help=True)
app.add_typer(settings_app, name="settings")
app.add_typer(memory_app, name="memory")

Project = Annotated[
    str | None,
    typer.Option(
        "--project", "-p", help="Project slug; default: the project containing this folder."
    ),
]


@settings_app.command("show")
def settings_show(project: Project = None) -> None:
    """Print the resolved settings as YAML."""
    with _errors():
        text = workspace.settings_yaml(project, Path.cwd())
    typer.echo(text, nl=False)


@settings_app.command("get")
def settings_get(
    key: Annotated[str, typer.Argument(help="Dotted key, e.g. loop_max.critical.")],
    project: Project = None,
) -> None:
    """Print one setting; lists and mappings print as JSON."""
    with _errors():
        value = workspace.setting(key, project, Path.cwd())
    typer.echo(value if isinstance(value, str) else json.dumps(value))


@settings_app.command("check")
def settings_check(project: Project = None) -> None:
    """Validate settings; prints problems only."""
    with _errors():
        problems = workspace.settings_problems(project, Path.cwd())
    for problem in problems:
        typer.echo(problem)
    if problems:
        raise typer.Exit(1)


@memory_app.command("add")
def memory_add(
    text: Annotated[str, typer.Argument(help="One fact, one line, about 20 words.")],
    why: Annotated[str, typer.Option("--why", help="Why this is worth remembering.")],
    section: Annotated[
        str, typer.Option(help="Working style, Goals, Preferences or Turned down.")
    ] = "Preferences",
    decision: Annotated[bool, typer.Option("--decision", help="Write to DECISIONS.md.")] = False,
    rejected: Annotated[
        str | None, typer.Option(help="With --decision: the alternative turned down.")
    ] = None,
    by: Annotated[str, typer.Option(envvar="HARNESS_AGENT", help="Who is writing.")] = "unknown",
    project: Project = None,
) -> None:
    """Remember one fact or one decision."""
    with _errors():
        result = workspace.remember(
            text,
            why,
            section=section,
            decision=decision,
            rejected=rejected,
            project=project,
            cwd=Path.cwd(),
            by=by,
        )
    if not result.added:
        typer.echo(f"{result.file}: already recorded")
        return
    typer.echo(f"{result.file} +1 line ({result.lines}/{result.cap})")
    if result.over_cap:
        typer.echo(f"warning: {result.file} is over its {result.cap}-line cap; compact it soon")


@memory_app.command("show")
def memory_show(
    decisions: Annotated[bool, typer.Option("--decisions", help="Show DECISIONS.md.")] = False,
    project: Project = None,
) -> None:
    """Print MEMORY.md, or the decisions of one project."""
    with _errors():
        text = workspace.recall(decisions, project, Path.cwd())
    typer.echo(text, nl=False)


@app.command()
def context(project: Project = None) -> None:
    """Print the conductor's digest: memory, process headings, open gates."""
    with _errors():
        text = workspace.context(project, Path.cwd())
    typer.echo(text, nl=False)
```

- [ ] **Step 4: Run the tests** — `uv run pytest tests/test_cli_workspace.py tests/test_cli.py tests/test_cli_projects.py` → `12 passed`. (`13/200` is the seeded MEMORY.md's 11 lines plus the entry and its blank line; update it if the seed file changes.)

- [ ] **Step 5: Update `docs/modules/cli/README.md`** — Interface gains "`harness settings show|get KEY|check`, `memory add TEXT --why WHY [--section S|--decision [--rejected R]] [--by NAME]`, `memory show [--decisions]`, `context`; all take `--project/-p` (default: the project containing the current folder)."; Changes gains on top "- 2026-10-22: `settings`, `memory` and `context` commands (SP2 M2)."

- [ ] **Step 6: Lint and commit** — as Task 1, message `feat(cli): settings, memory and context commands`, paths `src/super_harness/cli.py tests/test_cli_workspace.py docs/modules/cli`.

---

### Task 8: Contracts and status

**Files:** Modify `pyproject.toml`, `docs/architecture.md`, `AGENTS.md`.

- [ ] **Step 1: Extend the import contracts** — layers become `"super_harness.cli"`, `"super_harness.ops"`, `"super_harness.memory"`, `"super_harness.journal | super_harness.settings"`, `"super_harness.store"`, `"super_harness.model"`; the forbidden contract's `forbidden_modules` becomes `["super_harness.store", "super_harness.settings", "super_harness.memory", "super_harness.journal"]`. Run `make lint` → silent. If import-linter rejects the `|` syntax, split it into two layers `super_harness.journal` then `super_harness.settings`.

- [ ] **Step 2: Update status docs** — `docs/architecture.md` Status column: `settings`, `memory`, `journal` → "built (SP2 M2)"; `model` → "Plan, Ticket, Registry, Settings, Event, errors (SP2 M1–M2)"; `ops` → "`projects`, `workspace` (SP2 M1–M2); grows in M3, SP3, SP5"; `cli` → "`--version`, `init`, `doctor`, `link`, `adopt`, `settings`, `memory`, `context`"; the contracts sentence names the new layer order; Sub-projects row 2 → "in progress: M1 store core and M2 settings, memory, journal done; M3 plans and tickets next". `AGENTS.md` status line → "Status: sub-project 2 of 5 (Store + `harness` CLI), M1–M2 done: `harness init|doctor|link|adopt|settings|memory|context` work. `docs/architecture.md` tracks what is built."

- [ ] **Step 3: Full check and commit** — `make check` → exit 0, then `git add pyproject.toml docs/architecture.md AGENTS.md && git commit -m "build: layer contracts for settings, memory and journal" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`.
