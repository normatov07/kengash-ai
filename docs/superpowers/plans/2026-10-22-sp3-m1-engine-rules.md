# SP3 M1: Engine Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The pure engine rules (workflow routing and ticket scheduling), the model, settings and runtime files they need, and `harness next` on top of them.

**Architecture:** `workflow` and `scheduler` are pure modules that import only `model`: data in, decisions out. `store.runtime` keeps engine bookkeeping under `runtime/` (slots, last claims, pause flags). `ops.queue.next_tickets` reads tickets, settings and runtime files, asks `workflow` where each ready ticket would start and `scheduler` which may start now, and returns a dataclass that the CLI formats.

**Tech Stack:** Python 3.12, pydantic 2, Typer, pytest, import-linter, uv.

## Global Constraints

- Contract: `docs/superpowers/specs/2026-10-22-sp3-engine-design.md` (§2 decisions 6 and 17, §4, §6, §7, the `next` row of §10). Change the spec before changing a contract.
- A change to `src/super_harness/<module>` updates `docs/modules/<module>/README.md` in the same commit; `src/super_harness/store/defaults/SETTINGS.md` belongs to module `store`. `make docs` and the pre-commit hook enforce it.
- `workflow` and `scheduler` import only `model` (contract added in Task 4). `cli` imports only `ops` and `model`.
- `ops` functions return dataclasses; the CLI formats them. Status and action commands print at most 5 lines; `--json` prints everything.
- Docs under `docs/` stay ≤ 150 lines; AGENTS.md ≤ 100 lines.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- One test: `uv run pytest tests/test_x.py::test_name`; everything: `make check`.

---

### Task 1: Model and settings additions

**Files:**
- Modify: `src/super_harness/model/settings.py`, `src/super_harness/model/documents.py`, `src/super_harness/model/__init__.py`
- Modify: `src/super_harness/store/defaults/SETTINGS.md`
- Test: `tests/test_model_settings.py`, `tests/test_model.py`, `tests/test_settings.py`
- Docs: `docs/modules/model/README.md`, `docs/modules/store/README.md`

**Interfaces:**
- Produces: `PROVIDERS = ("claude", "codex", "antigravity", "gemini")`; `split_cli(cli: str) -> tuple[str, str | None]`; `ProviderOptions(allow_api_key: bool = False, user_config: bool = False)`; `Settings.providers: dict[str, ProviderOptions]`; `Settings.provider(name: str) -> ProviderOptions`; `Settings.memory.compactor: str = "claude/haiku"`; `Agent.bypass_permissions: bool = False`; `Ticket.step: str | None`; `Ticket.tokens_max: int | None`; `Review.session: SessionRef | None`; `"paused"` in `SUB_STATUSES[Folder.in_process]`. All exported from `super_harness.model`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_model_settings.py` and change its model import to `from super_harness.model import Event, ProviderOptions, Settings, split_cli`:

```python
def test_agents_and_fallbacks_name_known_providers() -> None:
    assert not Settings.model_validate({"agents": AGENTS}).agents["planner"].bypass_permissions
    planner = {"cli": "cluade/opus", "skill": "plan"}
    with pytest.raises(ValidationError, match="unknown provider 'cluade'"):
        Settings.model_validate({"agents": {**AGENTS, "planner": planner}})
    implementer = {"cli": "codex", "skill": "implement", "fallback": ["shell"]}
    with pytest.raises(ValidationError, match="unknown provider 'shell'"):
        Settings.model_validate({"agents": {**AGENTS, "implementer": implementer}})


def test_the_compactor_names_a_model_provider() -> None:
    assert Settings().memory.compactor == "claude/haiku"
    with pytest.raises(ValidationError, match="unknown provider 'llama'"):
        Settings.model_validate({"memory": {"compactor": "llama/3"}})


def test_provider_options_default_per_provider() -> None:
    settings = Settings.model_validate({"providers": {"codex": {"user_config": True}}})
    assert settings.provider("codex").user_config is True
    assert settings.provider("claude") == ProviderOptions()
    with pytest.raises(ValidationError, match=r"unknown providers \['cursor'\]"):
        Settings.model_validate({"providers": {"cursor": {}}})


def test_split_cli_separates_provider_and_model() -> None:
    assert split_cli("claude/opus") == ("claude", "opus")
    assert split_cli("codex") == ("codex", None)
```

Append to `tests/test_model.py` and add `Review, SessionRef` to its `super_harness.model` import:

```python
def test_tickets_record_their_step_and_token_budget() -> None:
    paused = ticket(status="in_process/paused", step="implement", tokens_max=300_000)
    assert (paused.sub_status, paused.step, paused.tokens_max) == ("paused", "implement", 300_000)
    assert "paused" in SUB_STATUSES[Folder.in_process]
    assert (ticket().step, ticket().tokens_max) == (None, None)
    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        ticket(tokens_max=0)


def test_plan_reviews_keep_their_reviewer_session() -> None:
    review = Review(round=1, verdict="fail", session=SessionRef(provider="codex", id="019a"))
    assert review.session == SessionRef(provider="codex", model="default", id="019a")
```

Append to `tests/test_settings.py`:

```python
def test_package_defaults_name_providers_and_the_compactor(store_paths: StorePaths) -> None:
    resolved = settings.load(store_paths)
    assert resolved.memory.compactor == "claude/haiku"
    assert set(resolved.providers) == {"claude", "codex", "antigravity"}
    assert not resolved.provider("claude").user_config
    assert not resolved.agents["implementer"].bypass_permissions
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run pytest tests/test_model_settings.py tests/test_model.py tests/test_settings.py`
Expected: collection errors, `ImportError: cannot import name 'ProviderOptions'`.

- [ ] **Step 3: Implement**

In `src/super_harness/model/settings.py`, import `field_validator` next to `model_validator` (`from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, field_validator, model_validator`) and add below `STEP_ROLES`:

```python
PROVIDERS = ("claude", "codex", "antigravity", "gemini")
SHELL = "shell"


def split_cli(cli: str) -> tuple[str, str | None]:
    """`claude/opus` → ("claude", "opus"); `codex` → ("codex", None): the CLI's default."""
    provider, _, model = cli.partition("/")
    return provider, model or None


def _known(cli: str, *, shell: bool = False) -> str:
    provider, _ = split_cli(cli)
    known = (*PROVIDERS, SHELL) if shell else PROVIDERS
    if provider not in known:
        raise ValueError(f"unknown provider {provider!r}; known: {', '.join(known)}")
    return cli
```

Replace `MemoryCaps` and `Agent`, and add `ProviderOptions` after `Agent`:

```python
class MemoryCaps(_Section):
    compact_at_lines: int = Field(200, ge=10)
    compactor: str = "claude/haiku"

    @field_validator("compactor")
    @classmethod
    def _model_provider(cls, value: str) -> str:
        return _known(value)


class Agent(_Section):
    on: bool = True
    cli: str
    skill: str
    blocking: bool = False
    fallback: list[str] = Field(default_factory=list)
    bypass_permissions: bool = False

    @field_validator("cli")
    @classmethod
    def _cli_provider(cls, value: str) -> str:
        return _known(value, shell=True)

    @field_validator("fallback")
    @classmethod
    def _fallback_providers(cls, value: list[str]) -> list[str]:
        for cli in value:
            _known(cli)
        return value


class ProviderOptions(_Section):
    allow_api_key: bool = False
    user_config: bool = False
```

In `Settings`, add the field between `review` and `agents`, and the validator and method after `_steps_have_agents`:

```python
    providers: dict[str, ProviderOptions] = Field(default_factory=dict)
```

```python
    @field_validator("providers")
    @classmethod
    def _provider_names(cls, value: dict[str, ProviderOptions]) -> dict[str, ProviderOptions]:
        unknown = sorted(set(value) - set(PROVIDERS))
        if unknown:
            raise ValueError(f"unknown providers {unknown}; known: {', '.join(PROVIDERS)}")
        return value

    def provider(self, name: str) -> ProviderOptions:
        """A provider's worker options; providers left out of SETTINGS get the defaults."""
        return self.providers.get(name, ProviderOptions())
```

In `src/super_harness/model/documents.py`: add `"paused",` before `"awaiting_merge",` in `SUB_STATUSES[Folder.in_process]`; move `class SessionRef` above `class Review`; then add to `Review` after `skipped: bool = False`:

```python
    session: SessionRef | None = None
```

In `Ticket`, add `step` right after `status` and `tokens_max` right after `tokens`:

```python
    step: str | None = None
```

```python
    tokens_max: int | None = Field(None, ge=1)
```

In `src/super_harness/model/__init__.py`, import `PROVIDERS, STEP_ROLES, Agent, ProviderOptions, Settings, Workflow, split_cli` from `super_harness.model.settings` and add `"PROVIDERS"` (after `"PLAN_SECTIONS"`), `"ProviderOptions"` (after `"ProjectEntry"`) and `"split_cli"` (before `"utc_now"`) to `__all__`.

In `src/super_harness/store/defaults/SETTINGS.md`, replace the lines from `memory.compact_at_lines: 200` through `agents:` with:

```yaml
memory.compact_at_lines: 200
memory.compactor: claude/haiku   # provider/model that compacts MEMORY.md
review.diff_only: true

# providers: allow_api_key keeps API-key variables in worker environments;
# user_config lets workers load your own hooks, plugins and MCP servers
providers:
  claude:      {allow_api_key: false, user_config: false}
  codex:       {allow_api_key: false, user_config: false}
  antigravity: {allow_api_key: false, user_config: false}

# agents: role → CLI; an omitted model means the CLI's default model;
# bypass_permissions: true adds the CLI's permission-bypass flag (off by default)
agents:
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest`
Expected: all pass.

- [ ] **Step 5: Update the module docs**

`docs/modules/model/README.md`: in the `Plan`, `Ticket`… bullet add "`Ticket.step` (the step running or next) and `Ticket.tokens_max` (empty: `tokens.per_ticket_max`); `Review.session`"; in the `SUB_STATUSES` bullet add "`in_process/paused`"; replace the `Settings` bullet with "- `Settings`, `Agent`, `Workflow`, `ProviderOptions`, `STEP_ROLES`, `PROVIDERS`, `split_cli`: the SETTINGS.md schema; workflows may only use known steps whose agents exist; an agent's `cli` names a provider or `shell`, while fallbacks and `memory.compactor` name a provider; `Settings.provider(name)` gives a provider's worker options, defaults included."; add the Changes line "- 2026-10-22: provider names checked, `ProviderOptions`, `memory.compactor`, `bypass_permissions`, ticket `step` and `tokens_max`, `paused`, `Review.session` (SP3 M1)."

`docs/modules/store/README.md`: add the Changes line "- 2026-10-22: default SETTINGS.md adds `memory.compactor`, `providers` and the `bypass_permissions` note (SP3 M1)."

- [ ] **Step 6: Commit**

```bash
make check
git add src/super_harness/model src/super_harness/store/defaults/SETTINGS.md tests/test_model_settings.py tests/test_model.py tests/test_settings.py docs/modules/model/README.md docs/modules/store/README.md
git commit -m "feat(model): provider settings, ticket step and token budget" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: Dependencies are met by merged or closed tickets

**Files:**
- Modify: `src/super_harness/ops/tickets.py` (`QUEUED` constant and `_met`)
- Test: `tests/test_ops_tickets.py`
- Docs: `docs/modules/ops/README.md`

**Interfaces:**
- Produces: `super_harness.ops.tickets.MET = ("done/merged", "done/closed")`; `_met` counts only those statuses (SP3 spec decision 6).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ops_tickets.py`:

```python
def test_a_branch_ready_dependency_keeps_dependents_blocked(
    store_paths: StorePaths, registered_repo: Path, make_ticket: Callable[..., Doc[Ticket]]
) -> None:
    documents.save_ticket(
        store_paths.project("payments-api"), make_ticket(status="done/branch_ready")
    )
    batch = "- {title: Follow-up, importance: simple, depends_on: [7b55e0c1]}"
    added = tickets.add_tickets(plan_for(registered_repo), batch, project=None, by="x")
    follow_up = added.tickets[0]
    assert follow_up.status == "in_queue/blocked"
    moved = tickets.move_ticket("7b55e0c1", "done/merged", "merged", project=None, by="x")
    assert moved.ready == [follow_up.id]
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/test_ops_tickets.py::test_a_branch_ready_dependency_keeps_dependents_blocked`
Expected: FAIL, `assert 'in_queue/ready' == 'in_queue/blocked'`.

- [ ] **Step 3: Implement**

In `src/super_harness/ops/tickets.py`, add below `QUEUED`:

```python
MET = ("done/merged", "done/closed")  # dependents start from merged code (SP3 spec decision 6)
```

and replace `_met`:

```python
def _met(depends_on: Iterable[str], tickets: Mapping[str, Doc[Ticket]]) -> bool:
    """True when every dependency is a ticket of this project that is merged or closed."""
    return all(dep in tickets and tickets[dep].meta.status in MET for dep in depends_on)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_ops_tickets.py tests/test_cli_tickets.py`
Expected: all pass (`done` alone still means `done/closed`, which counts).

- [ ] **Step 5: Update the docs**

`docs/modules/ops/README.md` Invariants: change "a ticket is `ready` only when every dependency is done" to "a ticket is `ready` only when every dependency is merged or closed (`done/branch_ready` keeps dependents blocked)", and "`in_process` needs every dependency done" to "`in_process` needs every dependency merged or closed". Changes: "- 2026-10-22: dependencies are met only by `done/merged` and `done/closed` (SP3 M1)."

- [ ] **Step 6: Commit**

```bash
make check
git add src/super_harness/ops/tickets.py tests/test_ops_tickets.py docs/modules/ops/README.md
git commit -m "feat(ops): only merged or closed tickets unblock dependents" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3: Runtime files: slots, claims, pause flags

**Files:**
- Create: `src/super_harness/model/runtime.py`, `src/super_harness/store/runtime.py`
- Modify: `src/super_harness/model/__init__.py`, `src/super_harness/store/paths.py`
- Test: `tests/test_runtime.py`
- Docs: `docs/modules/model/README.md`, `docs/modules/store/README.md`

**Interfaces:**
- Produces: model `SlotEntry(provider, project, ticket, step, pid, since)`, `SlotTable(held, waiting)`, `Claims(last: dict[str, datetime])`; `StorePaths.slots`, `.claims`, `.flags`; `store.runtime.load_slots(paths) -> SlotTable`, `save_slots(paths, table)`, `load_claims(paths) -> Claims`, `save_claims(paths, claims)`, `Pause(everything=False, projects=frozenset())` with `covers(slug) -> bool`, `pause_state(paths) -> Pause`, `set_pause(paths, slug: str | None, *, on: bool)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_runtime.py`:

```python
from datetime import UTC, datetime

import pytest

from super_harness.model import Claims, HarnessError, SlotEntry, SlotTable
from super_harness.store import StorePaths, runtime

NOW = datetime(2026, 10, 22, 9, 41, tzinfo=UTC)


def test_slots_and_claims_start_empty_and_round_trip(store_paths: StorePaths) -> None:
    assert runtime.load_slots(store_paths) == SlotTable()
    assert runtime.load_claims(store_paths) == Claims()
    held = SlotEntry(
        provider="claude", project="app", ticket="7b55e0c1", step="plan", pid=42, since=NOW
    )
    runtime.save_slots(store_paths, SlotTable(held=[held]))
    runtime.save_claims(store_paths, Claims(last={"app": NOW}))
    assert runtime.load_slots(store_paths).held == [held]
    assert runtime.load_claims(store_paths).last == {"app": NOW}


def test_pause_flags_cover_one_project_or_everything(store_paths: StorePaths) -> None:
    assert not runtime.pause_state(store_paths).covers("app")
    runtime.set_pause(store_paths, "app", on=True)
    assert runtime.pause_state(store_paths) == runtime.Pause(projects=frozenset({"app"}))
    runtime.set_pause(store_paths, None, on=True)
    assert runtime.pause_state(store_paths).covers("web")
    runtime.set_pause(store_paths, None, on=False)
    runtime.set_pause(store_paths, "app", on=False)
    assert runtime.pause_state(store_paths) == runtime.Pause()


def test_a_damaged_runtime_file_names_itself(store_paths: StorePaths) -> None:
    store_paths.slots.parent.mkdir(parents=True)
    store_paths.slots.write_text("{", encoding="utf-8")
    with pytest.raises(HarnessError, match=r"slots\.json: damaged runtime file"):
        runtime.load_slots(store_paths)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_runtime.py`
Expected: `ImportError: cannot import name 'Claims'`.

- [ ] **Step 3: Implement**

Create `src/super_harness/model/runtime.py`:

```python
"""Engine bookkeeping files under runtime/ (SP3 spec §4); never versioned."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from super_harness.model.core import utc_now


class _Runtime(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SlotEntry(_Runtime):
    """A provider session one step holds, or waits for."""

    provider: str
    project: str
    ticket: str
    step: str
    pid: int
    since: datetime = Field(default_factory=utc_now)


class SlotTable(_Runtime):
    """runtime/slots.json: held slots, and waiting steps in arrival order."""

    held: list[SlotEntry] = Field(default_factory=list)
    waiting: list[SlotEntry] = Field(default_factory=list)


class Claims(_Runtime):
    """runtime/claims.json: when each project last had a ticket claimed."""

    last: dict[str, datetime] = Field(default_factory=dict)
```

Export `Claims`, `SlotEntry`, `SlotTable` from `src/super_harness/model/__init__.py` (import from `super_harness.model.runtime`; add to `__all__` in sorted order).

Add to `StorePaths` in `src/super_harness/store/paths.py`, after `locks`:

```python
    @property
    def slots(self) -> Path:
        return self.runtime / "slots.json"

    @property
    def claims(self) -> Path:
        return self.runtime / "claims.json"

    @property
    def flags(self) -> Path:
        return self.runtime / "flags"
```

Create `src/super_harness/store/runtime.py`:

```python
"""Engine bookkeeping under runtime/: slots, last claims and pause flags (SP3 spec §4)."""

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ValidationError

from super_harness.model import Claims, HarnessError, SlotTable
from super_harness.store.files import atomic_write
from super_harness.store.paths import StorePaths

PAUSE = "pause"


@dataclass(frozen=True)
class Pause:
    """Pause flags: `everything`, or single projects."""

    everything: bool = False
    projects: frozenset[str] = frozenset()

    def covers(self, slug: str) -> bool:
        return self.everything or slug in self.projects


def load_slots(paths: StorePaths) -> SlotTable:
    return _load(paths.slots, SlotTable)


def save_slots(paths: StorePaths, table: SlotTable) -> None:
    _save(paths.slots, table)


def load_claims(paths: StorePaths) -> Claims:
    return _load(paths.claims, Claims)


def save_claims(paths: StorePaths, claims: Claims) -> None:
    _save(paths.claims, claims)


def pause_state(paths: StorePaths) -> Pause:
    """`flags/pause` pauses everything; `flags/pause-<slug>` pauses one project."""
    if not paths.flags.is_dir():
        return Pause()
    names = {flag.name for flag in paths.flags.iterdir()}
    prefix = f"{PAUSE}-"
    projects = frozenset(name.removeprefix(prefix) for name in names if name.startswith(prefix))
    return Pause(PAUSE in names, projects)


def set_pause(paths: StorePaths, slug: str | None, *, on: bool) -> None:
    """Pause or resume one project, or everything when `slug` is None."""
    flag = paths.flags / (PAUSE if slug is None else f"{PAUSE}-{slug}")
    if on:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.touch()
    else:
        flag.unlink(missing_ok=True)


def _load[M: BaseModel](path: Path, model: type[M]) -> M:
    if not path.exists():
        return model()
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        problem = exc.errors()[0]["msg"]
        raise HarnessError(f"{path}: damaged runtime file ({problem}); delete it to reset") from exc


def _save(path: Path, data: BaseModel) -> None:
    atomic_write(path, data.model_dump_json(indent=2) + "\n")
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_runtime.py`
Expected: 3 passed.

- [ ] **Step 5: Update the module docs**

`docs/modules/model/README.md` Interface: "- `SlotEntry`, `SlotTable`, `Claims`: `runtime/slots.json` and `runtime/claims.json` (SP3 spec §4)." Changes: "- 2026-10-22: runtime file schemas (SP3 M1)."

`docs/modules/store/README.md` Interface: "- `runtime`: `load_slots`/`save_slots` (`runtime/slots.json`), `load_claims`/`save_claims` (`runtime/claims.json`), `pause_state` → `Pause(everything, projects)` and `set_pause(paths, slug or None, on=)` (`runtime/flags/`); a damaged file raises an error naming it." Add `slots`, `claims`, `flags` to the `StorePaths` bullet. Changes: "- 2026-10-22: runtime slots, claims and pause flags (SP3 M1)."

- [ ] **Step 6: Commit**

```bash
make check
git add src/super_harness/model src/super_harness/store/paths.py src/super_harness/store/runtime.py tests/test_runtime.py docs/modules/model/README.md docs/modules/store/README.md
git commit -m "feat(store): runtime slots, claims and pause flags" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 4: `workflow`: step routing

**Files:**
- Create: `src/super_harness/workflow.py`, `docs/modules/workflow/README.md`
- Modify: `pyproject.toml` (import contract)
- Test: `tests/test_workflow.py`

**Interfaces:**
- Consumes: `Settings`, `STEP_ROLES` from `super_harness.model`.
- Produces (module `super_harness.workflow`): constants `NEEDS_APPROVAL`, `STALLED`, `FAILED`, `AWAITING_MERGE`, `PARKED`, `BRANCH_READY` (full statuses); `Approval = Literal["loop_cap", "token_cap", "approve_step"]`; frozen dataclasses `Progress(workflow, hitl, step: str | None, loop, loop_max, tokens, tokens_max, streaks: Mapping[str, Mapping[str, int]] = {}, plan_rounds: int = 0)`, `Outcome(verdict: Literal["pass", "fail"], fingerprints: tuple[str, ...] = ())`, `Run(step, loop)`, `Halt(status, reason, approval: Approval | None = None)`, `Merge()`, `Routed(decision: Run | Halt | Merge, progress: Progress)`; functions `steps_for(settings, workflow, *, hitl) -> list[str]`, `first_step(settings, workflow, *, hitl) -> str | None`, `blocking_off(settings, workflow) -> str | None`, `before(settings, progress) -> Routed`, `after(settings, progress, outcome) -> Routed`, `approve(settings, progress, approval, *, loops=None, tokens=None) -> Routed`, `fingerprint(file, issue) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_workflow.py`:

```python
from typing import Any

from super_harness.model import Settings
from super_harness.workflow import (
    AWAITING_MERGE,
    BRANCH_READY,
    FAILED,
    NEEDS_APPROVAL,
    PARKED,
    STALLED,
    Halt,
    Merge,
    Outcome,
    Progress,
    Run,
    after,
    approve,
    before,
    fingerprint,
    steps_for,
)

AGENTS: dict[str, Any] = {
    "planner": {"cli": "claude/opus", "skill": "plan"},
    "plan-reviewer": {"cli": "codex", "skill": "review-plan"},
    "implementer": {"cli": "codex", "skill": "implement"},
    "code-reviewer": {"cli": "claude/opus", "skill": "review-code"},
    "security-reviewer": {"cli": "claude/sonnet", "skill": "review-security", "blocking": True},
}
WORKFLOWS: dict[str, Any] = {
    "standard": {
        "steps": ["plan", "review_plan", "implement", "review_code"],
        "on_fail": {"review_plan": "plan", "review_code": "implement"},
    },
    "critical": {
        "steps": ["plan", "review_plan", "implement", "review_code", "security"],
        "on_fail": {"review_plan": "plan", "review_code": "implement", "security": "implement"},
    },
    "bare": {"steps": ["implement", "review_code"]},
}
PASS = Outcome("pass")
DONE = Halt(AWAITING_MERGE, "every step passed")


def settings(agents: dict[str, Any] | None = None, **fields: Any) -> Settings:
    data = {"agents": AGENTS | (agents or {}), "workflows": WORKFLOWS} | fields
    return Settings.model_validate(data)


def off(role: str) -> dict[str, Any]:
    return {role: AGENTS[role] | {"on": False}}


def progress(step: str | None = "review_code", **fields: Any) -> Progress:
    base: dict[str, Any] = {
        "workflow": "standard",
        "hitl": False,
        "step": step,
        "loop": 1,
        "loop_max": 4,
        "tokens": 0,
        "tokens_max": 250_000,
    }
    return Progress(**(base | fields))


def fail(*fingerprints: str) -> Outcome:
    return Outcome("fail", fingerprints)


def test_effective_steps_skip_off_roles_and_add_approval() -> None:
    full = ["plan", "review_plan", "implement", "review_code"]
    assert steps_for(settings(), "standard", hitl=False) == full
    assert steps_for(settings(off("code-reviewer")), "standard", hitl=False) == full[:3]
    no_review = settings(plan={"review_max": 0})
    assert steps_for(no_review, "standard", hitl=False) == ["plan", "implement", "review_code"]
    assert steps_for(settings(), "standard", hitl=True) == ["plan", "approve", *full[1:]]
    assert steps_for(settings(), "bare", hitl=True) == ["approve", "implement", "review_code"]


def test_before_runs_the_step_or_halts_at_a_gate() -> None:
    assert before(settings(), progress()).decision == Run("review_code", 1)
    capped = before(settings(), progress(tokens=250_000)).decision
    assert capped == Halt(NEEDS_APPROVAL, "token cap: 250000 of 250000", "token_cap")
    gate = before(settings(), progress("approve", hitl=True)).decision
    assert gate == Halt(NEEDS_APPROVAL, "waiting for the user's approval", "approve_step")


def test_a_blocking_role_that_is_off_fails_the_ticket() -> None:
    routed = before(settings(off("security-reviewer")), progress(workflow="critical"))
    assert routed.decision == Halt(FAILED, "role security-reviewer is off and blocking")


def test_a_step_whose_role_was_switched_off_is_skipped() -> None:
    routed = before(settings(off("plan-reviewer")), progress("review_plan"))
    assert (routed.decision, routed.progress.step) == (Run("implement", 1), "implement")
    assert before(settings(off("code-reviewer")), progress()).decision == DONE
    unknown = before(settings(), progress("docs"))
    assert unknown.decision == Halt(FAILED, "workflow standard has no step docs")


def test_a_pass_moves_on_and_the_last_pass_follows_merge_mode() -> None:
    assert after(settings(), progress("implement"), PASS).decision == Run("review_code", 1)
    assert after(settings(), progress(), PASS).decision == DONE
    assert after(settings(merge={"mode": "auto"}), progress(), PASS).decision == Merge()
    branch = after(settings(merge={"mode": "branch"}), progress(), PASS)
    waiting = "every step passed; the branch waits for the user"
    assert (branch.decision, branch.progress.step) == (Halt(BRANCH_READY, waiting), None)
    hitl = progress(hitl=True)
    assert after(settings(merge={"mode": "auto"}), hitl, PASS).decision == DONE


def test_a_failing_review_recirculates_with_one_more_loop() -> None:
    routed = after(settings(), progress(), fail("a1"))
    assert routed.decision == Run("implement", 2)
    assert (routed.progress.step, routed.progress.loop) == ("implement", 2)
    assert routed.progress.streaks == {"review_code": {"a1": 1}}


def test_a_failure_at_the_loop_cap_asks_the_user_or_parks() -> None:
    routed = after(settings(), progress(loop=4), fail("a1"))
    assert routed.decision == Halt(NEEDS_APPROVAL, "loop cap: 4 of 4", "loop_cap")
    assert (routed.progress.step, routed.progress.loop) == ("implement", 4)
    parked = after(settings(loop_ask_at_cap=False), progress(loop=4), fail("a1"))
    assert parked.decision == Halt(PARKED, "loop cap: 4 of 4")


def test_the_same_finding_failing_twice_in_a_row_stalls() -> None:
    seen = progress(streaks={"review_code": {"a1": 1}})
    stalled = after(settings(), seen, fail("a1", "b2"))
    assert stalled.decision == Halt(STALLED, "same finding failed 2 loops in a row: a1")
    moved_on = after(settings(), seen, fail("b2"))
    assert moved_on.decision == Run("implement", 2)
    assert moved_on.progress.streaks == {"review_code": {"b2": 1}}
    assert after(settings(), seen, PASS).progress.streaks == {"review_code": {}}


def test_plan_review_rounds_are_capped_by_plan_review_max() -> None:
    first = after(settings(), progress("review_plan"), fail("p1"))
    assert (first.decision, first.progress.plan_rounds) == (Run("plan", 2), 1)
    second = after(settings(), progress("review_plan", loop=2, plan_rounds=1), fail("p2"))
    assert second.decision == Halt(STALLED, "plan review failed 2 rounds (plan.review_max: 2)")


def test_plan_review_failures_can_leave_the_loop_count_alone() -> None:
    lenient = settings(loop_count_rejected_review=False)
    assert after(lenient, progress("review_plan", loop=4), fail("p1")).decision == Run("plan", 4)


def test_a_failure_without_an_on_fail_edge_fails_the_ticket() -> None:
    routed = after(settings(), progress(workflow="bare"), fail("a1"))
    assert routed.decision == Halt(FAILED, "review_code failed and has no on_fail step")


def test_approvals_grant_loops_tokens_or_pass_the_approval_step() -> None:
    capped = progress("implement", loop=4)
    looped = approve(settings(), capped, "loop_cap")
    assert (looped.decision, looped.progress.loop_max) == (Run("implement", 5), 6)
    assert approve(settings(), capped, "loop_cap", loops=5).progress.loop_max == 9
    spent = progress(tokens=260_000)
    assert approve(settings(), spent, "token_cap").progress.tokens_max == 510_000
    assert approve(settings(), spent, "token_cap", tokens=1000).progress.tokens_max == 261_000
    passed = approve(settings(), progress("approve", hitl=True), "approve_step")
    assert passed.decision == Run("review_plan", 1)


def test_fingerprints_ignore_case_numbers_and_spacing() -> None:
    one = fingerprint("./src/keys.py", "Missing check  on line 12")
    assert one == fingerprint("src/keys.py", "missing check on line 40")
    assert one != fingerprint("src/other.py", "missing check on line 12")
    assert len(one) == 12
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_workflow.py`
Expected: `ModuleNotFoundError: No module named 'super_harness.workflow'`.

- [ ] **Step 3: Implement**

Create `src/super_harness/workflow.py`:

```python
"""Step routing per workflow: effective steps, caps, stalls and approvals (SP3 spec §6).

Pure functions of the resolved settings and a ticket's progress; callers do the I/O.
"""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Literal

from super_harness.model import STEP_ROLES, Settings

Approval = Literal["loop_cap", "token_cap", "approve_step"]
Verdict = Literal["pass", "fail"]

NEEDS_APPROVAL = "in_process/needs_approval"
STALLED = "in_process/stalled"
FAILED = "in_process/failed"
AWAITING_MERGE = "in_process/awaiting_merge"
PARKED = "in_queue/parked"
BRANCH_READY = "done/branch_ready"
REVIEWS = frozenset({"review_plan", "review_code", "security"})

_DIGITS = re.compile(r"[0-9]+")
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class Progress:
    """Where a ticket stands between steps; `step` is None once every step has passed."""

    workflow: str
    hitl: bool
    step: str | None
    loop: int
    loop_max: int
    tokens: int
    tokens_max: int
    streaks: Mapping[str, Mapping[str, int]] = field(default_factory=dict)
    plan_rounds: int = 0


@dataclass(frozen=True)
class Outcome:
    """A finished step: its verdict and the fingerprints of its findings."""

    verdict: Verdict
    fingerprints: tuple[str, ...] = ()


@dataclass(frozen=True)
class Run:
    """Run `step` at `loop`."""

    step: str
    loop: int


@dataclass(frozen=True)
class Halt:
    """Stop at `status`; `approval` names what `harness approve` grants, if anything."""

    status: str
    reason: str
    approval: Approval | None = None


@dataclass(frozen=True)
class Merge:
    """Every step passed under `merge.mode: auto`: merge if the main working tree allows."""


@dataclass(frozen=True)
class Routed:
    """A decision and the progress to store with it."""

    decision: Run | Halt | Merge
    progress: Progress


def steps_for(settings: Settings, workflow: str, *, hitl: bool) -> list[str]:
    """The steps a ticket runs: roles that are off are skipped, `review_plan` is dropped at
    `plan.review_max: 0`, and hitl tickets get `approve` after `plan` (first without one)."""
    steps = [
        step
        for step in settings.workflows[workflow].steps
        if _on(settings, step) and not (step == "review_plan" and settings.plan.review_max == 0)
    ]
    if hitl and "approve" not in steps:
        steps.insert(steps.index("plan") + 1 if "plan" in steps else 0, "approve")
    return steps


def first_step(settings: Settings, workflow: str, *, hitl: bool) -> str | None:
    steps = steps_for(settings, workflow, hitl=hitl)
    return steps[0] if steps else None


def blocking_off(settings: Settings, workflow: str) -> str | None:
    """The first role of the workflow that is switched off although it is blocking."""
    for step in settings.workflows[workflow].steps:
        role = STEP_ROLES[step]
        if role is not None and settings.agents[role].blocking and not settings.agents[role].on:
            return role
    return None


def before(settings: Settings, progress: Progress) -> Routed:
    """Check the ticket's step before it runs: blocking roles, the token cap, approval."""
    role = blocking_off(settings, progress.workflow)
    if role is not None:
        return Routed(Halt(FAILED, f"role {role} is off and blocking"), progress)
    step = progress.step
    if step is None:
        return _end(settings, progress)
    if step not in steps_for(settings, progress.workflow, hitl=progress.hitl):
        if step not in settings.workflows[progress.workflow].steps:
            reason = f"workflow {progress.workflow} has no step {step}"
            return Routed(Halt(FAILED, reason), progress)
        following = _next(settings, progress, step)  # its role was switched off
        if following is None:
            return _end(settings, progress)
        step = following
    now = replace(progress, step=step)
    if now.tokens >= now.tokens_max:
        reason = f"token cap: {now.tokens} of {now.tokens_max}"
        return Routed(Halt(NEEDS_APPROVAL, reason, "token_cap"), now)
    if step == "approve":
        return Routed(Halt(NEEDS_APPROVAL, "waiting for the user's approval", "approve_step"), now)
    return Routed(Run(step, now.loop), now)


def after(settings: Settings, progress: Progress, outcome: Outcome) -> Routed:
    """Route the step that just ran (`progress.step`): the first matching rule of §6 wins."""
    step = progress.step
    if step is None:
        raise ValueError("after() needs the step that ran")
    now = _count(progress, step, outcome)
    if outcome.verdict == "pass":
        following = _next(settings, now, step)
        if following is None:
            return _end(settings, now)
        return Routed(Run(following, now.loop), replace(now, step=following))
    return _failed(settings, now, step)


def approve(
    settings: Settings,
    progress: Progress,
    approval: Approval,
    *,
    loops: int | None = None,
    tokens: int | None = None,
) -> Routed:
    """What the user's approval grants: more loops and the pending recirculation, more
    tokens, or passing the approval step."""
    if approval == "approve_step":
        return after(settings, progress, Outcome("pass"))
    if approval == "loop_cap":
        grant = loops or settings.loop_grant
        now = replace(progress, loop_max=progress.loop_max + grant, loop=progress.loop + 1)
    else:
        grant = tokens or settings.tokens.per_ticket_max
        now = replace(progress, tokens_max=progress.tokens + grant)
    return before(settings, now)


def fingerprint(file: str, issue: str) -> str:
    """Identify a finding across loops by its path and text, ignoring case, numbers and spacing."""
    path = file.strip().replace("\\", "/").removeprefix("./")
    text = _SPACES.sub(" ", _DIGITS.sub("0", issue.lower())).strip()
    digest = hashlib.sha1(f"{path}\n{text}".encode(), usedforsecurity=False)
    return digest.hexdigest()[:12]


def _on(settings: Settings, step: str) -> bool:
    role = STEP_ROLES[step]
    return role is None or settings.agents[role].on


def _next(settings: Settings, progress: Progress, step: str) -> str | None:
    """The first step that runs after `step`, in workflow order."""
    steps = steps_for(settings, progress.workflow, hitl=progress.hitl)
    if step in steps:
        later = steps[steps.index(step) + 1 :]
    else:
        order = settings.workflows[progress.workflow].steps
        later = [name for name in order[order.index(step) + 1 :] if name in steps]
    return later[0] if later else None


def _end(settings: Settings, progress: Progress) -> Routed:
    done = replace(progress, step=None)
    if progress.hitl or settings.merge.mode == "ask":
        return Routed(Halt(AWAITING_MERGE, "every step passed"), done)
    if settings.merge.mode == "auto":
        return Routed(Merge(), done)
    return Routed(Halt(BRANCH_READY, "every step passed; the branch waits for the user"), done)


def _count(progress: Progress, step: str, outcome: Outcome) -> Progress:
    """Fold a review outcome into the stall streaks and the failing plan-review rounds."""
    if step not in REVIEWS:
        return progress
    failing = outcome.verdict == "fail"
    previous = progress.streaks.get(step, {})
    streak = {fp: previous.get(fp, 0) + 1 for fp in outcome.fingerprints} if failing else {}
    rounds = progress.plan_rounds
    if failing and step == "review_plan":
        rounds += 1
    return replace(progress, streaks={**progress.streaks, step: streak}, plan_rounds=rounds)


def _failed(settings: Settings, progress: Progress, step: str) -> Routed:
    limit = settings.plan.review_max
    if step == "review_plan" and progress.plan_rounds >= limit:
        reason = f"plan review failed {progress.plan_rounds} rounds (plan.review_max: {limit})"
        return Routed(Halt(STALLED, reason), progress)
    streak = progress.streaks.get(step, {})
    repeated = sorted(fp for fp, runs in streak.items() if runs >= settings.stall_repeat)
    if repeated:
        reason = f"same finding failed {settings.stall_repeat} loops in a row: "
        return Routed(Halt(STALLED, reason + ", ".join(repeated)), progress)
    target = settings.workflows[progress.workflow].on_fail.get(step)
    if target is None:
        return Routed(Halt(FAILED, f"{step} failed and has no on_fail step"), progress)
    back = replace(progress, step=target)
    if step == "review_plan" and not settings.loop_count_rejected_review:
        return Routed(Run(target, back.loop), back)
    if back.loop < back.loop_max:
        back = replace(back, loop=back.loop + 1)
        return Routed(Run(target, back.loop), back)
    reason = f"loop cap: {back.loop} of {back.loop_max}"
    if settings.loop_ask_at_cap:
        return Routed(Halt(NEEDS_APPROVAL, reason, "loop_cap"), back)
    return Routed(Halt(PARKED, reason), back)
```

Add to `pyproject.toml` after the last import-linter contract:

```toml
[[tool.importlinter.contracts]]
name = "Engine rules are pure: workflow and scheduler import only model"
type = "forbidden"
source_modules = ["super_harness.workflow"]
forbidden_modules = [
    "super_harness.cli",
    "super_harness.ops",
    "super_harness.memory",
    "super_harness.journal",
    "super_harness.settings",
    "super_harness.store",
]
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_workflow.py && make lint`
Expected: 13 passed; lint quiet.

- [ ] **Step 5: Write `docs/modules/workflow/README.md`**

```markdown
# workflow

## Purpose

Decide what a ticket does next (SP3 spec §6): which steps its workflow runs, when a cap, a stall or an approval stops it, and where a failing review sends it. Pure: settings and progress in, decisions out.

## Interface

- `steps_for(settings, workflow, hitl=)`: the effective steps; roles that are off are skipped, `review_plan` is dropped at `plan.review_max: 0`, hitl tickets get `approve` after `plan`. `first_step(...)` is the first of them.
- `blocking_off(settings, workflow)`: a blocking role that is switched off.
- `before(settings, progress)` → `Routed`: run the step, or halt at the token cap or the approval step; a step whose role was switched off is skipped.
- `after(settings, progress, outcome)` → `Routed`: route a finished step; the first matching rule of SP3 spec §6 wins.
- `approve(settings, progress, approval, loops=, tokens=)` → `Routed`: what `harness approve` grants.
- `fingerprint(file, issue)`: 12 hex digits naming a finding across loops.
- Types: `Progress(workflow, hitl, step, loop, loop_max, tokens, tokens_max, streaks, plan_rounds)`, `Outcome(verdict, fingerprints)`, decisions `Run(step, loop)`, `Halt(status, reason, approval)`, `Merge()`, and `Routed(decision, progress)`.

## Invariants

- Imports only `model`; no I/O and no clock.
- `loop` grows only on a failing verdict with an `on_fail` edge, or when a loop cap is approved; a `review_plan` failure keeps it while `loop_count_rejected_review` is false.
- Stall streaks count consecutive failing runs of one review step per fingerprint; a pass clears that step's streaks.
- `Halt.approval` is set exactly when `harness approve` can open the gate.

## Changes

- 2026-10-22: effective steps, caps, stalls, approvals, fingerprints (SP3 M1).
```

- [ ] **Step 6: Commit**

```bash
make check
git add src/super_harness/workflow.py tests/test_workflow.py pyproject.toml docs/modules/workflow/README.md
git commit -m "feat(workflow): pure step routing with caps, stalls and approvals" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 5: `scheduler`: the runnable set

**Files:**
- Create: `src/super_harness/scheduler.py`, `docs/modules/scheduler/README.md`
- Modify: `pyproject.toml` (add the module to the Task 4 contract)
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `Importance` from `super_harness.model`.
- Produces (module `super_harness.scheduler`): frozen dataclasses `Candidate(id, project, importance: Importance, created: datetime, touches: tuple[str, ...], provider: str | None)`, `Busy(id, project, touches)`, `Limits(total: int, per_provider: Mapping[str, int])`; `Held(project, provider)` (NamedTuple); `Selection(chosen: list[Candidate], held_back: dict[str, str])`; `overlaps(a, b) -> bool`; `select(candidates, busy, held, machine, projects, last_claims) -> Selection`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scheduler.py`:

```python
from datetime import UTC, datetime, timedelta

from super_harness.model import Importance
from super_harness.scheduler import Busy, Candidate, Held, Limits, overlaps, select

T0 = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)
ROOMY = Limits(total=8, per_provider={"claude": 8, "codex": 8})


def candidate(
    ticket_id: str,
    project: str = "app",
    importance: Importance = Importance.standard,
    *,
    age: int = 0,
    touches: tuple[str, ...] = ("src",),
    provider: str | None = "claude",
) -> Candidate:
    created = T0 - timedelta(minutes=age)
    return Candidate(ticket_id, project, importance, created, touches, provider)


def test_paths_overlap_by_whole_segments() -> None:
    assert not overlaps(["services/web"], ["services/webhooks"])
    assert overlaps(["services"], ["services/web/app.py"])
    assert overlaps(["./a/b/"], ["a/b/c"])
    assert overlaps([], ["docs"])
    assert overlaps(["."], ["docs"])
    assert not overlaps(["a", "b"], ["c"])


def test_running_and_chosen_tickets_keep_their_paths() -> None:
    picks = select(
        [
            candidate("t1", touches=("src/api",)),
            candidate("t2", touches=("src/api/v2",)),
            candidate("t3", touches=("docs",)),
            candidate("t4", "web", touches=("src",)),
        ],
        busy=[Busy("r1", "app", ("docs",))],
        held=[],
        machine=ROOMY,
        projects={},
        last_claims={},
    )
    assert [c.id for c in picks.chosen] == ["t1", "t4"]
    assert picks.held_back == {"t2": "touches overlap t1", "t3": "touches overlap r1"}


def test_slots_are_counted_per_machine_and_per_project() -> None:
    machine = Limits(total=8, per_provider={"claude": 2, "codex": 3})
    web = Limits(total=1, per_provider={"codex": 3})
    picks = select(
        [
            candidate("a1", touches=("a",)),
            candidate("a2", touches=("b",)),
            candidate("w1", "web", touches=("a",), provider="codex"),
            candidate("w2", "web", touches=("b",), provider="codex"),
            candidate("w3", "web", touches=("c",), provider=None),
        ],
        busy=[],
        held=[Held("other", "claude")],
        machine=machine,
        projects={"web": web},
        last_claims={},
    )
    assert [c.id for c in picks.chosen] == ["a1", "w1", "w3"]
    assert picks.held_back == {"a2": "no free claude slot", "w2": "no free codex slot"}


def test_projects_take_turns_and_critical_tickets_go_first() -> None:
    picks = select(
        [
            candidate("a1", touches=("x",), age=5),
            candidate("a2", importance=Importance.critical, touches=("y",)),
            candidate("a3", touches=("z",), age=9),
            candidate("w1", "web", Importance.simple, touches=("x",)),
        ],
        busy=[],
        held=[],
        machine=ROOMY,
        projects={},
        last_claims={"app": T0},
    )
    assert [c.id for c in picks.chosen] == ["w1", "a2", "a3", "a1"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_scheduler.py`
Expected: `ModuleNotFoundError: No module named 'super_harness.scheduler'`.

- [ ] **Step 3: Implement**

Create `src/super_harness/scheduler.py`:

```python
"""Which ready tickets may start now: overlap, slots and project turns (SP3 spec §7).

Pure: callers pass tickets, running work and limits in, and get a selection back.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import zip_longest
from typing import NamedTuple

from super_harness.model import Importance

RANK = {Importance.critical: 0, Importance.standard: 1, Importance.simple: 2}
NEVER = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True)
class Candidate:
    """A ready ticket; `provider` is the CLI its first step needs (None: no slot)."""

    id: str
    project: str
    importance: Importance
    created: datetime
    touches: tuple[str, ...]
    provider: str | None


@dataclass(frozen=True)
class Busy:
    """An in_process ticket: it keeps its paths until it leaves in_process."""

    id: str
    project: str
    touches: tuple[str, ...]


class Held(NamedTuple):
    """A provider session that a running step holds."""

    project: str
    provider: str


@dataclass(frozen=True)
class Limits:
    """`sessions.max` and `sessions.per_provider` of one settings scope."""

    total: int
    per_provider: Mapping[str, int]


@dataclass
class Selection:
    chosen: list[Candidate] = field(default_factory=list)
    held_back: dict[str, str] = field(default_factory=dict)


def overlaps(a: Sequence[str], b: Sequence[str]) -> bool:
    """Path prefixes overlap when one contains the other, segment by segment; an empty
    list stands for the whole repo."""
    if not a or not b:
        return True
    return any(_within(x, y) or _within(y, x) for x in a for y in b)


def select(
    candidates: Sequence[Candidate],
    busy: Sequence[Busy],
    held: Sequence[Held],
    machine: Limits,
    projects: Mapping[str, Limits],
    last_claims: Mapping[str, datetime],
) -> Selection:
    """Walk candidates in turn order; keep each one that overlaps nothing running or chosen
    in its project and fits a free slot on this machine and in its project."""
    selection = Selection()
    taken = list(busy)
    used = list(held)
    for candidate in _in_turns(candidates, last_claims):
        clash = next(
            (
                other.id
                for other in taken
                if other.project == candidate.project
                and overlaps(other.touches, candidate.touches)
            ),
            None,
        )
        if clash is not None:
            selection.held_back[candidate.id] = f"touches overlap {clash}"
            continue
        provider = candidate.provider
        if provider is not None:
            own = [slot for slot in used if slot.project == candidate.project]
            limits = projects.get(candidate.project, machine)
            if not (_fits(provider, used, machine) and _fits(provider, own, limits)):
                selection.held_back[candidate.id] = f"no free {provider} slot"
                continue
            used.append(Held(candidate.project, provider))
        selection.chosen.append(candidate)
        taken.append(Busy(candidate.id, candidate.project, candidate.touches))
    return selection


def _fits(provider: str, used: Sequence[Held], limits: Limits) -> bool:
    same = sum(slot.provider == provider for slot in used)
    return len(used) < limits.total and same < limits.per_provider.get(provider, 0)


def _in_turns(
    candidates: Sequence[Candidate], last_claims: Mapping[str, datetime]
) -> list[Candidate]:
    """Projects take turns, the one with the oldest last claim first; inside a project,
    critical before standard before simple, then oldest first."""
    queues: dict[str, list[Candidate]] = {}
    for candidate in sorted(candidates, key=lambda c: (RANK[c.importance], c.created, c.id)):
        queues.setdefault(candidate.project, []).append(candidate)
    order = sorted(queues, key=lambda slug: (last_claims.get(slug, NEVER), slug))
    turns = zip_longest(*(queues[slug] for slug in order))
    return [candidate for turn in turns for candidate in turn if candidate is not None]


def _segments(path: str) -> list[str]:
    return [part for part in path.strip().split("/") if part not in ("", ".")]


def _within(inner: str, outer: str) -> bool:
    """True when `inner` lies inside `outer`, or is it."""
    prefix = _segments(outer)
    return _segments(inner)[: len(prefix)] == prefix
```

In `pyproject.toml`, change the Task 4 contract's `source_modules` to `["super_harness.workflow", "super_harness.scheduler"]`.

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_scheduler.py && make lint`
Expected: 4 passed; lint quiet.

- [ ] **Step 5: Write `docs/modules/scheduler/README.md`**

```markdown
# scheduler

## Purpose

Pick which ready tickets may start now (SP3 spec §7): no `touches` overlap inside a project, a free provider slot on the machine and in the project, and fair turns between projects. Pure: tickets, running work and limits in, a selection out.

## Interface

- `overlaps(a, b)`: path prefixes overlap when one contains the other segment by segment; an empty list is the whole repo.
- `select(candidates, busy, held, machine, projects, last_claims)` → `Selection(chosen, held_back)`; `held_back` maps a ticket id to `touches overlap <id>` or `no free <provider> slot`.
- Types: `Candidate(id, project, importance, created, touches, provider)` (`provider` None: the step needs no slot), `Busy(id, project, touches)`, `Held(project, provider)`, `Limits(total, per_provider)`.

## Invariants

- Imports only `model`; no I/O and no clock.
- Turn order: projects by oldest last claim (never claimed first, then by slug); inside a project critical, standard, simple, then oldest, then id.
- A chosen ticket holds its paths and its slot for the rest of the walk, so one selection never holds two overlapping tickets of a project or more sessions than the limits allow.

## Changes

- 2026-10-22: overlap, slots, project turns (SP3 M1).
```

- [ ] **Step 6: Commit**

```bash
make check
git add src/super_harness/scheduler.py tests/test_scheduler.py pyproject.toml docs/modules/scheduler/README.md
git commit -m "feat(scheduler): runnable set with overlap, slots and project turns" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 6: `harness next`

**Files:**
- Create: `src/super_harness/ops/queue.py`
- Modify: `src/super_harness/cli.py` (import, `Every` alias, `_capped`, `status` uses it, new `next` command)
- Test: `tests/test_ops_queue.py`, `tests/test_cli_queue.py`
- Docs: `docs/modules/ops/README.md`, `docs/modules/cli/README.md`, `docs/architecture.md`, `AGENTS.md`

**Interfaces:**
- Consumes: `workflow.Progress`, `workflow.before`, `workflow.first_step`, `workflow.Run`, `workflow.Halt` (Task 4); `scheduler.Candidate`, `Busy`, `Held`, `Limits`, `select` (Task 5); `runtime.pause_state`, `load_slots`, `load_claims` (Task 3); `split_cli`, `STEP_ROLES` (Task 1); `records.scope`, `records.project_tickets`, `workspace.GATES` (SP2).
- Produces: `ops.queue.NextTicket(id, project, importance, step, provider, title)`; `ops.queue.Queue(runnable, held_back, blocked, running, gates, paused)`; `ops.queue.next_tickets(project: str | None = None) -> Queue`; `ops.queue.progress_of(resolved: Settings, ticket: Ticket) -> workflow.Progress` (reused by M3).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ops_queue.py`:

```python
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from super_harness.model import Claims, Doc, SlotEntry, SlotTable, Ticket
from super_harness.ops import projects, queue
from super_harness.store import StorePaths, documents, runtime

NOW = datetime(2026, 10, 22, 9, 41, tzinfo=UTC)
Make = Callable[..., Doc[Ticket]]


def add_web_project(tmp_path: Path, run_git: Callable[..., str]) -> None:
    path = tmp_path / "code" / "web"
    path.mkdir(parents=True)
    run_git(path, "init", "-q", "-b", "main")
    run_git(path, "commit", "-q", "--allow-empty", "-m", "init")
    projects.init_project(path)


def test_projects_take_turns(
    store_paths: StorePaths,
    registered_repo: Path,
    tmp_path: Path,
    run_git: Callable[..., str],
    make_ticket: Make,
) -> None:
    add_web_project(tmp_path, run_git)
    payments = store_paths.project("payments-api")
    documents.save_ticket(payments, make_ticket(touches=["a"]))
    documents.save_ticket(payments, make_ticket("a91b3d07", touches=["b"]))
    simple = make_ticket("3c9d0e11", project="web", importance="simple", workflow="simple")
    documents.save_ticket(store_paths.project("web"), simple)
    runtime.save_claims(store_paths, Claims(last={"payments-api": NOW}))
    found = queue.next_tickets()
    assert [(t.id, t.project, t.step, t.provider) for t in found.runnable] == [
        ("3c9d0e11", "web", "plan", "claude"),
        ("7b55e0c1", "payments-api", "plan", "claude"),
        ("a91b3d07", "payments-api", "plan", "claude"),
    ]
    assert [t.id for t in queue.next_tickets("payments-api").runnable] == ["7b55e0c1", "a91b3d07"]


def test_slots_pauses_and_settings_hold_tickets_back(
    store_paths: StorePaths, registered_repo: Path, make_ticket: Make
) -> None:
    project = store_paths.project("payments-api")
    documents.save_ticket(project, make_ticket(touches=["a"]))
    documents.save_ticket(project, make_ticket("a91b3d07", touches=["b"], workflow="nope"))
    held = [
        SlotEntry(provider="claude", project="other", ticket=f"0000000{n}", step="plan", pid=n)
        for n in range(3)
    ]
    runtime.save_slots(store_paths, SlotTable(held=held))
    found = queue.next_tickets()
    assert found.runnable == []
    assert found.held_back == {
        "7b55e0c1": "no free claude slot",
        "a91b3d07": "settings have no workflow 'nope'",
    }
    runtime.set_pause(store_paths, "payments-api", on=True)
    assert queue.next_tickets().held_back == {"7b55e0c1": "paused", "a91b3d07": "paused"}
    runtime.set_pause(store_paths, "payments-api", on=False)
    runtime.save_slots(store_paths, SlotTable())
    text = project.settings.read_text(encoding="utf-8")
    off = text.replace("security-reviewer: {on: true,", "security-reviewer: {on: false,")
    project.settings.write_text(off, encoding="utf-8")
    held_back = queue.next_tickets().held_back
    assert held_back["7b55e0c1"] == "role security-reviewer is off and blocking"
```

Create `tests/test_cli_queue.py`:

```python
import json
from collections.abc import Callable
from pathlib import Path

from typer.testing import CliRunner

from super_harness.cli import app
from super_harness.model import Doc, Ticket
from super_harness.store import StorePaths, documents

runner = CliRunner()
Make = Callable[..., Doc[Ticket]]


def test_next_lists_runnable_tickets(
    inside_registered_repo: Path, store_paths: StorePaths, make_ticket: Make
) -> None:
    project = store_paths.project("payments-api")
    documents.save_ticket(project, make_ticket(touches=["services/webhooks"]))
    documents.save_ticket(project, make_ticket("a91b3d07", touches=["services/webhooks/keys"]))
    result = runner.invoke(app, ["next"])
    assert result.exit_code == 0
    assert result.stdout == "7b55e0c1 payments-api critical plan→claude Rotate keys\n"
    data = json.loads(runner.invoke(app, ["next", "--json"]).stdout)
    assert data["held_back"] == {"a91b3d07": "touches overlap 7b55e0c1"}


def test_next_says_why_nothing_can_run(
    inside_registered_repo: Path, store_paths: StorePaths, make_ticket: Make
) -> None:
    assert runner.invoke(app, ["next"]).stdout == "nothing runnable: the queue is empty\n"
    project = store_paths.project("payments-api")
    gate = make_ticket(status="in_process/needs_approval", step="implement")
    documents.save_ticket(project, gate)
    blocked = make_ticket("a91b3d07", status="in_queue/blocked", depends_on=["7b55e0c1"])
    documents.save_ticket(project, blocked)
    documents.save_ticket(project, make_ticket("3c9d0e11"))
    result = runner.invoke(app, ["next"])
    assert result.stdout == "nothing runnable: 1 held back, 1 blocked, 1 at gates\n"


def test_next_prints_at_most_five_lines(
    inside_registered_repo: Path, store_paths: StorePaths, make_ticket: Make
) -> None:
    project = store_paths.project("payments-api")
    for path in (store_paths.defaults / "SETTINGS.md", project.settings):
        roomy = path.read_text(encoding="utf-8").replace("claude: 3", "claude: 8")
        path.write_text(roomy, encoding="utf-8")
    for number in range(7):
        documents.save_ticket(project, make_ticket(f"aaaaaaa{number}", touches=[f"d{number}"]))
    lines = runner.invoke(app, ["next"]).stdout.splitlines()
    assert len(lines) == 5
    assert lines[-1] == "+3 more; run: harness next --json"
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_ops_queue.py tests/test_cli_queue.py`
Expected: `ImportError: cannot import name 'queue' from 'super_harness.ops'`.

- [ ] **Step 3: Implement `ops.queue`**

Create `src/super_harness/ops/queue.py`:

```python
"""What can start now: ready tickets that pass the scheduler's rules (SP3 spec §7)."""

from dataclasses import dataclass, field

from super_harness import scheduler, settings, workflow
from super_harness.model import STEP_ROLES, Folder, Gate, Settings, Ticket, split_cli
from super_harness.ops import records
from super_harness.ops.workspace import GATES
from super_harness.store import runtime
from super_harness.store.paths import StorePaths

NO_SLOT = ("shell", "user")  # run_tests steps and the user's approval need no session


@dataclass
class NextTicket:
    id: str
    project: str
    importance: str
    step: str
    provider: str
    title: str


@dataclass
class Queue:
    runnable: list[NextTicket] = field(default_factory=list)
    held_back: dict[str, str] = field(default_factory=dict)
    blocked: int = 0
    running: int = 0
    gates: int = 0
    paused: int = 0


def next_tickets(project: str | None = None) -> Queue:
    """Tickets to start now, in start order: of every project, or of the named one."""
    paths = StorePaths.default()
    machine = settings.load(paths)
    pause = runtime.pause_state(paths)
    found = Queue()
    candidates: list[scheduler.Candidate] = []
    busy: list[scheduler.Busy] = []
    limits: dict[str, scheduler.Limits] = {}
    starts: dict[str, tuple[Ticket, str, str]] = {}
    for slug in records.scope(paths, project):
        resolved = settings.load(paths, slug)
        limits[slug] = _limits(resolved)
        for doc in records.project_tickets(paths, slug).values():
            ticket = doc.meta
            if ticket.folder is Folder.in_process:
                busy.append(scheduler.Busy(ticket.id, slug, tuple(ticket.touches)))
                _count(found, ticket.sub_status)
            elif ticket.status == "in_queue/blocked":
                found.blocked += 1
            elif ticket.status == "in_queue/ready":
                step, problem = _start(resolved, ticket, paused=pause.covers(slug))
                if step is None:
                    found.held_back[ticket.id] = problem
                    continue
                provider = _provider(resolved, step)
                starts[ticket.id] = (ticket, step, provider)
                slot = None if provider in NO_SLOT else provider
                touches = tuple(ticket.touches)
                candidates.append(
                    scheduler.Candidate(
                        ticket.id, slug, ticket.importance, ticket.created, touches, slot
                    )
                )
    slots = runtime.load_slots(paths)
    held = [scheduler.Held(entry.project, entry.provider) for entry in slots.held]
    claims = runtime.load_claims(paths).last
    selection = scheduler.select(candidates, busy, held, _limits(machine), limits, claims)
    found.held_back |= selection.held_back
    for candidate in selection.chosen:
        ticket, step, provider = starts[candidate.id]
        found.runnable.append(
            NextTicket(
                ticket.id, candidate.project, ticket.importance.value, step, provider, ticket.title
            )
        )
    return found


def progress_of(resolved: Settings, ticket: Ticket) -> workflow.Progress:
    """The ticket's place in its workflow; a ticket that never ran starts at the first step."""
    hitl = ticket.gate is Gate.hitl
    first = workflow.first_step(resolved, ticket.workflow, hitl=hitl)
    return workflow.Progress(
        workflow=ticket.workflow,
        hitl=hitl,
        step=ticket.step or first,
        loop=ticket.loop,
        loop_max=ticket.loop_max,
        tokens=ticket.tokens,
        tokens_max=ticket.tokens_max or resolved.tokens.per_ticket_max,
    )


def _start(resolved: Settings, ticket: Ticket, *, paused: bool) -> tuple[str | None, str]:
    """The step a claim would start with, or None and the reason the ticket waits."""
    if paused:
        return None, "paused"
    if ticket.workflow not in resolved.workflows:
        return None, f"settings have no workflow {ticket.workflow!r}"
    decision = workflow.before(resolved, progress_of(resolved, ticket)).decision
    if isinstance(decision, workflow.Run):
        return decision.step, ""
    if isinstance(decision, workflow.Halt) and decision.approval == "approve_step":
        return "approve", ""
    return None, decision.reason if isinstance(decision, workflow.Halt) else "every step passed"


def _provider(resolved: Settings, step: str) -> str:
    """The CLI a step runs on: a provider, `shell`, or `user` for the approval step."""
    role = STEP_ROLES.get(step)
    if role is None:
        return "user"
    provider, _ = split_cli(resolved.agents[role].cli)
    return provider


def _limits(resolved: Settings) -> scheduler.Limits:
    return scheduler.Limits(resolved.sessions.max, resolved.sessions.per_provider)


def _count(found: Queue, sub_status: str) -> None:
    if sub_status in GATES:
        found.gates += 1
    elif sub_status == "paused":
        found.paused += 1
    else:
        found.running += 1
```

- [ ] **Step 4: Implement the CLI command**

In `src/super_harness/cli.py`: import `queue` with the other ops modules (`from super_harness.ops import plans, projects, queue, status, tickets, workspace`). Next to `MAX_LINES`, add:

```python
Every = Annotated[
    str | None,
    typer.Option("--project", "-p", help="Only this project; default: every project."),
]


def _capped(lines: list[str], command: str) -> list[str]:
    """At most MAX_LINES lines; the last one says how many more `command` shows."""
    if len(lines) <= MAX_LINES:
        return lines
    more = len(lines) - MAX_LINES + 1
    return [*lines[: MAX_LINES - 1], f"+{more} more; run: {command}"]
```

Change `show_status` to take `project: Every = None` and to end with:

```python
    if not lines:
        lines = ["no projects; run: harness init"]
    for line in _capped(lines, "harness status --json"):
        typer.echo(line)
```

Add after `show_status`:

```python
@app.command("next")
def show_next(project: Every = None, as_json: AsJson = False) -> None:
    """Tickets that can start now, in the order to start them."""
    with _errors():
        found = queue.next_tickets(project)
    if as_json:
        _emit_json(found)
        return
    lines = [
        f"{item.id} {item.project} {item.importance} {item.step}→{item.provider} {item.title}"
        for item in found.runnable
    ] or [_nothing_runnable(found)]
    for line in _capped(lines, "harness next --json"):
        typer.echo(line)


def _nothing_runnable(found: queue.Queue) -> str:
    counts = [
        f"{count} {label}"
        for count, label in (
            (len(found.held_back), "held back"),
            (found.blocked, "blocked"),
            (found.running, "running"),
            (found.gates, "at gates"),
            (found.paused, "paused"),
        )
        if count
    ]
    return f"nothing runnable: {', '.join(counts) or 'the queue is empty'}"
```

- [ ] **Step 5: Run the tests to see them pass**

Run: `uv run pytest tests/test_ops_queue.py tests/test_cli_queue.py tests/test_cli_tickets.py`
Expected: all pass (the `status` output is unchanged).

- [ ] **Step 6: Update the docs**

`docs/modules/ops/README.md` Interface: "- `queue.next_tickets(project=None)` → `Queue(runnable, held_back, blocked, running, gates, paused)`: `runnable` holds `NextTicket(id, project, importance, step, provider, title)` in start order (`provider` is `shell` or `user` when the step needs no session); `held_back` maps each waiting ready ticket to its reason. `queue.progress_of(settings, ticket)` → `workflow.Progress`." Changes: "- 2026-10-22: `queue.next_tickets` (SP3 M1)."

`docs/modules/cli/README.md` Interface: "- `harness next [--project SLUG]`: tickets that can start now, one `<id> <project> <importance> <step>→<provider> <title>` line each, at most 5; otherwise why nothing can run (`--json`: everything, reasons included)." Changes: "- 2026-10-22: `next` command (SP3 M1)."

`docs/architecture.md`: in the Modules table add `next` to the `cli` status; `model` status gains "runtime files, provider options (SP3 M1)"; `store` status becomes "built (SP2 M1); runtime slots, claims, pause flags (SP3 M1)"; `ops` status gains "`queue` (SP3 M1)"; `scheduler` and `workflow` statuses become "built (SP3 M1)". Append to the import-linter sentence: "; `workflow` and `scheduler` import only `model`". Sub-project 3 row: "in progress: spec `docs/superpowers/specs/2026-10-22-sp3-engine-design.md`; M1 engine rules built; M2 providers and git next".

`AGENTS.md` status line: add `next` to the command list (`…|ticket|status|next` work).

- [ ] **Step 7: Check the whole milestone and commit**

Run: `make check`
Expected: exit 0, quiet.

Then walk it with the real CLI in a scratch store, from the repo root:

```bash
h="$PWD/.venv/bin/harness"
export HARNESS_HOME="$(mktemp -d)/h"
demo="$(mktemp -d)/demo" && mkdir -p "$demo" && git -C "$demo" init -q -b main
git -C "$demo" -c user.name=t -c user.email=t@t commit -q --allow-empty -m init
"$h" init "$demo" && cd "$demo"
plan=$(printf 'Demo.\n' | "$h" plan new --title Demo --mode direct | cut -d' ' -f2)
"$h" plan approve "$plan" --skip-review
printf -- '- {title: One, importance: simple, touches: [src]}\n- {title: Two, importance: simple, touches: [src/app]}\n' | "$h" ticket add --plan "$plan"
"$h" next            # one line: <id> demo simple plan→claude One
"$h" next --json     # held_back: {"<id of Two>": "touches overlap <id of One>"}
cd - && unset HARNESS_HOME
```

Expected: the outputs in the comments. Then commit:

```bash
git add src/super_harness/ops/queue.py src/super_harness/cli.py tests/test_ops_queue.py tests/test_cli_queue.py docs/modules/ops/README.md docs/modules/cli/README.md docs/architecture.md AGENTS.md
git commit -m "feat(cli): harness next lists the tickets that can start now" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## M1 exit (SP3 spec §1)

- Unit tests cover every row of SP3 spec §6 (`tests/test_workflow.py`) and every `next` rule of §7 (`tests/test_scheduler.py`, `tests/test_ops_queue.py`).
- `harness next` filters and orders tickets (`tests/test_cli_queue.py`, plus the scratch-store walk).
- Review every change against the spec before M2 starts (AGENTS.md hard rule 9).
