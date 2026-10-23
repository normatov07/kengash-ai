# SP3 M3: Workers and Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detached workers that run a ticket's steps through the provider adapters, and the conductor's controls around them: `run`, `wait`, `approve`, `park`, `stop`, `pause`, `resume`, `merge`, `ticket changes`, `ticket attach`, the dead-worker check and conductor pings.

**Architecture:** `ops.steps.run_job` is the step loop of SP3 spec §5: it asks `workflow` where to go, picks the agent (`ops.agents`), takes a slot (`ops.slots`), builds the prompt (`ops.prompts`), calls an adapter, commits through `gitops`, writes the ticket and journal, and routes. `ops.controls` claims tickets and starts `python -m super_harness.worker`, a thin frontend that heartbeats and calls `run_job`. `ops.merging`, `ops.waiting` and `ops.changes` hold the other use cases; `ops.lifecycle` holds the status changes they share. Engine bookkeeping lives in `runtime/`.

**Tech Stack:** Python 3.12, pydantic 2, Typer, subprocess, filelock, pytest, import-linter, uv.

**Spec:** `docs/superpowers/specs/2026-10-22-sp3-engine-design.md` (§2 decisions 1, 2, 5, 7–13, 17, 18, 20; §4; §5; §8.2; §9; §10; §11), with system spec `2026-10-22-super-harness-design.md` §5, §6, §6.1 and §7.1.

## Global Constraints

- The spec is the contract; Task 1 records the decisions this plan takes where the spec is silent.
- A change to `src/super_harness/<module>` updates `docs/modules/<module>/README.md` in the same commit (`make docs` and the pre-commit hook enforce it); `worker` gets a new README.
- Import layers become `cli | worker > ops > memory > journal | settings > store > model`; `worker` reaches the store only through `ops`; `ops` never imports `worker` (it starts it as a process).
- Only `harness` writes store files. Ticket writes happen under `runtime/locks/<slug>.lock`; lock order is project lock → `repo-<slug>.lock` → `slots.lock` → `git.lock`.
- `ops` functions return dataclasses; the CLI formats them. Status and action commands print at most 5 lines (`_capped`); `--json` prints everything.
- Exit codes: 0 ok · 1 error · 3 wait timeout · 4 setup needed (`NeedsSetup`) · 5 user decision.
- Journal events follow system spec §6.1; Handoff, Findings and journal text pass through the redactor.
- No test runs a real provider: the autouse `fake_clis` fixture (`tests/conftest.py`) puts the fakes first on `PATH`; detached workers inherit that environment.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- One test: `uv run pytest tests/test_x.py::test_name`; everything: `make check`.

## Review Focus

1. The user moves a ticket (e.g. `ticket move X done`) while its worker runs a step: the worker must keep the user's status and drop the step's result (Task 6).
2. A worker killed with SIGKILL mid-step: `next` or `wait` marks the ticket `failed` "worker died", and `run` resumes it at its step with its sessions (Tasks 10 and 7).
3. Two `run` calls for one ticket: the second is skipped, never a second worker (Task 7).
4. `wait` with nothing running in scope returns `idle` at once instead of sleeping to the timeout (Task 10).
5. A CLI that hangs past `step_timeout_min` twice: the step fails with the log path instead of retrying forever (Task 6).

---

### Task 1: Record the M3 decisions in the spec

**Files:**
- Modify: `docs/superpowers/specs/2026-10-22-sp3-engine-design.md` (§2: append decisions 21–27)

- [ ] **Step 1: Append to §2**

```markdown
21. **Claims count queued slots.** `run` re-checks overlap and slots under the locks, counting held and queued slots, and queues the claimed ticket's first slot, so two conductors cannot overbook a provider.
22. **Stopping.** `run` writes `workers/<id>.json` before it returns. A worker never writes a stopped state: `stop` waits for it to exit, then marks the ticket `failed` "stopped" and frees its slots.
23. **Merge conflicts** send the ticket to `in_queue/ready` at `implement` with loop + 1 (at the loop cap: `needs_approval`), with a finding listing the conflicted files; the conductor runs it again.
24. **`wait` events** are the journal events `ticket.needs_approval`, `ticket.stalled`, `ticket.failed`, `ticket.awaiting_merge`, `ticket.merged`, and `ticket.moved` into `done/`; each carries `status`, `loop`, `loop_max` and `reason`. The cursor is a journal position (day file and line).
25. **Resumed sessions** get the open Findings on work steps, and the latest Handoff plus the diff stat on review steps. `## Findings` holds the latest review step's findings; a pass clears it.
26. **The user wins.** When a ticket leaves `in_process` (or changes step) while its worker runs, the worker drops the step's result, frees its slot and exits.
27. **Deferred park.** `park` on a running ticket prints `ticket <id> → in_queue/parked after its step`; the worker parks it before its next step.
```

- [ ] **Step 2: Check and commit**

Run: `make docs`
Expected: no output.

```bash
git add docs/superpowers/specs/2026-10-22-sp3-engine-design.md
git commit -m "docs: SP3 spec decisions for workers and controls"
```

---

### Task 2: Runtime state and journal positions

**Files:**
- Modify: `src/super_harness/model/runtime.py`, `src/super_harness/model/__init__.py`, `src/super_harness/store/paths.py`, `src/super_harness/store/runtime.py`, `src/super_harness/journal.py`
- Test: `tests/test_runtime.py`, `tests/test_journal.py`
- Docs: `docs/modules/model/README.md`, `docs/modules/store/README.md`, `docs/modules/journal/README.md`

**Interfaces:**
- Produces (models exported from `super_harness.model`):
  - `WorkerRecord(id: str, project: str, pid: int, job: Literal["ticket"] = "ticket", step: str | None = None, started: datetime = utc_now(), heartbeat: datetime = utc_now())`
  - `Running(role: str, provider: str, model: str | None = None, log: Path)`: a CLI call in flight.
  - `TicketState(streaks: dict[str, dict[str, int]] = {}, plan_rounds: int = 0, approval: Literal["loop_cap", "token_cap", "approve_step"] | None = None, start_commit: str | None = None, totals: dict[str, Usage] = {}, running: Running | None = None, calls: int = 0)`
  - `ConductorPing(pid: int, agent: str, project: str | None, time: datetime)`; `JournalCursor(day: str = "", line: int = 0)`.
  - `StorePaths`: `workers`, `ticket_states`, `conductors`, `logs` (all under `runtime/`), `worktrees` (`<home>/worktrees`), `worktree(slug: str, ticket_id: str) -> Path` (`worktrees/<slug>/hrn-<id>`).
  - `store.runtime`: `load_worker(paths, id) -> WorkerRecord | None`, `load_workers(paths) -> list[WorkerRecord]`, `save_worker(paths, record)`, `drop_worker(paths, id)`, `beat(paths, id)` and `set_worker_step(paths, id, step: str | None)` (both no-ops without a record; serialised by a module `threading.Lock`), `load_ticket_state(paths, id) -> TicketState`, `save_ticket_state(paths, id, state)`, `drop_ticket_state(paths, id)`, `set_park(paths, id, *, on: bool)`, `park_requested(paths, id) -> bool` (`flags/park-<id>`), `save_ping(paths, ping)` (`conductors/<pid>.json`), `load_cursor(paths, scope) -> JournalCursor | None` and `save_cursor(paths, scope, cursor)` (`conductors/cursor-<scope>.json`).
  - `journal.read_after(paths, cursor: JournalCursor) -> tuple[list[Event], JournalCursor]` (events after the cursor, in order, and the cursor at the end); `journal.end(paths) -> JournalCursor`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_runtime.py`:

```python
def test_worker_records_beat_and_drop(store_paths: StorePaths) -> None:
    runtime.save_worker(store_paths, WorkerRecord(id="7b55e0c1", project="payments-api", pid=4242))
    before = runtime.load_worker(store_paths, "7b55e0c1")
    assert before is not None and before.step is None
    runtime.set_worker_step(store_paths, "7b55e0c1", "implement")
    runtime.beat(store_paths, "7b55e0c1")
    after = runtime.load_worker(store_paths, "7b55e0c1")
    assert after is not None and after.step == "implement" and after.heartbeat >= before.heartbeat
    assert [w.id for w in runtime.load_workers(store_paths)] == ["7b55e0c1"]
    runtime.drop_worker(store_paths, "7b55e0c1")
    runtime.beat(store_paths, "7b55e0c1")
    assert runtime.load_worker(store_paths, "7b55e0c1") is None


def test_ticket_state_park_flags_and_cursors(store_paths: StorePaths) -> None:
    assert runtime.load_ticket_state(store_paths, "7b55e0c1") == TicketState()
    state = TicketState(plan_rounds=1, totals={"doc-writer": Usage(input=5)})
    runtime.save_ticket_state(store_paths, "7b55e0c1", state)
    assert runtime.load_ticket_state(store_paths, "7b55e0c1") == state
    runtime.set_park(store_paths, "7b55e0c1", on=True)
    assert runtime.park_requested(store_paths, "7b55e0c1")
    runtime.set_park(store_paths, "7b55e0c1", on=False)
    assert not runtime.park_requested(store_paths, "7b55e0c1")
    assert runtime.load_cursor(store_paths, "all") is None
    runtime.save_cursor(store_paths, "all", JournalCursor(day="2026-10-23", line=4))
    assert runtime.load_cursor(store_paths, "all") == JournalCursor(day="2026-10-23", line=4)
    assert store_paths.worktree("payments-api", "7b55e0c1") == (
        store_paths.home / "worktrees" / "payments-api" / "hrn-7b55e0c1"
    )
```

Append to `tests/test_journal.py`:

```python
def test_read_after_returns_each_event_once(store_paths: StorePaths) -> None:
    start = journal.end(store_paths)
    assert start == JournalCursor()
    journal.append(store_paths, Event(ts=datetime(2026, 10, 22, 23, 59, tzinfo=UTC), type="a"))
    journal.append(store_paths, Event(ts=datetime(2026, 10, 23, 0, 1, tzinfo=UTC), type="b"))
    events, cursor = journal.read_after(store_paths, start)
    assert [e.type for e in events] == ["a", "b"] and cursor == JournalCursor("2026-10-23", 1)
    journal.append(store_paths, Event(ts=datetime(2026, 10, 23, 0, 2, tzinfo=UTC), type="c"))
    events, cursor = journal.read_after(store_paths, cursor)
    assert [e.type for e in events] == ["c"] and cursor == journal.end(store_paths)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_runtime.py tests/test_journal.py`
Expected: FAIL with `ImportError` (`WorkerRecord`, `JournalCursor`).

- [ ] **Step 3: Implement** the models, paths, store functions and journal functions in Interfaces. `read_after` reads day files whose stem is ≥ `cursor.day`, skipping the first `cursor.line` lines of the cursor's own day; `end` is the last day file and its line count (`JournalCursor()` when the journal is empty). Runtime files use the existing `_load`/`_save` helpers.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_runtime.py tests/test_journal.py && make lint type`
Expected: PASS.

- [ ] **Step 5: Document and commit** (model: the runtime models; store: the runtime layout and functions; journal: `read_after`, `end`)

```bash
git add src/super_harness/ tests/test_runtime.py tests/test_journal.py docs/modules/
git commit -m "feat(store): worker records, ticket engine state, conductor files, journal positions"
```

---

### Task 3: Slots: claims queue, workers take them in arrival order

**Files:**
- Modify: `src/super_harness/scheduler.py` (make `_fits` public as `fits` with the project check folded in)
- Create: `src/super_harness/ops/slots.py`
- Test: `tests/test_scheduler.py`, `tests/test_ops_slots.py`
- Docs: `docs/modules/scheduler/README.md`, `docs/modules/ops/README.md`

**Interfaces:**
- Consumes: `SlotEntry`, `SlotTable`, `runtime.load_slots/save_slots`, `settings.load`.
- Produces:
  - `scheduler.fits(provider: str, project: str, used: Sequence[Held], machine: Limits, projects: Mapping[str, Limits]) -> bool` (machine-wide and per-project limits; `select` uses it).
  - `ops.slots.limits(paths: StorePaths) -> tuple[scheduler.Limits, dict[str, scheduler.Limits]]` (defaults scope and every project).
  - `ops.slots.occupied(paths, *, exclude: str | None = None) -> list[scheduler.Held]`: held and queued slots, minus the ticket `exclude`.
  - `ops.slots.queue_slot(paths, entry: SlotEntry) -> None`: append a waiter unless the ticket already holds or waits.
  - `ops.slots.acquire(paths, entry: SlotEntry) -> bool`: under `slots.lock`, true when the ticket holds a slot after the call. Its waiter (added or updated to `entry`'s provider, step and pid) becomes held when every earlier waiter that fits has been granted first.
  - `ops.slots.release(paths, ticket_id: str) -> None`: drop the ticket's held and queued entries.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_scheduler.py`:

```python
def test_fits_checks_machine_and_project_limits() -> None:
    machine = Limits(3, {"claude": 2})
    projects = {"a": Limits(1, {"claude": 1})}
    assert fits("claude", "b", [Held("a", "claude")], machine, projects)
    assert not fits("claude", "a", [Held("a", "claude")], machine, projects)
    assert not fits("claude", "b", [Held("a", "claude"), Held("b", "claude")], machine, projects)
    assert not fits("codex", "b", [], machine, projects)
```

`tests/test_ops_slots.py` (one claude slot machine-wide, written to the defaults scope with the `write_settings` helper pattern of `tests/test_ops_providers.py`):

```python
def entry(ticket: str, provider: str = "claude") -> SlotEntry:
    return SlotEntry(provider=provider, project="payments-api", ticket=ticket, step="plan", pid=1)


def test_waiters_take_freed_slots_in_arrival_order(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    write_settings(store_paths, "sessions.per_provider: {claude: 1, codex: 1}\n")
    slots.queue_slot(store_paths, entry("aaaaaaaa"))
    slots.queue_slot(store_paths, entry("bbbbbbbb"))
    assert not slots.acquire(store_paths, entry("bbbbbbbb"))  # aaaaaaaa came first
    assert slots.acquire(store_paths, entry("cccccccc", "codex"))  # another provider is free
    assert slots.acquire(store_paths, entry("aaaaaaaa"))
    assert slots.acquire(store_paths, entry("aaaaaaaa"))  # holding already
    assert not slots.acquire(store_paths, entry("bbbbbbbb"))
    slots.release(store_paths, "aaaaaaaa")
    assert slots.acquire(store_paths, entry("bbbbbbbb"))
    table = runtime.load_slots(store_paths)
    assert [e.ticket for e in table.held] == ["cccccccc", "bbbbbbbb"] and table.waiting == []


def test_occupied_counts_held_and_queued(registered_repo: Path, store_paths: StorePaths) -> None:
    slots.queue_slot(store_paths, entry("aaaaaaaa"))
    slots.acquire(store_paths, entry("bbbbbbbb"))
    assert len(slots.occupied(store_paths)) == 2
    assert slots.occupied(store_paths, exclude="aaaaaaaa") == [Held("payments-api", "claude")]
```

`write_settings` here replaces both the defaults and the project SETTINGS.md, as in `tests/test_ops_providers.py`; move that helper into `tests/conftest.py` as a plain function and import it from both files.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_scheduler.py tests/test_ops_slots.py`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement** `scheduler.fits` (and use it in `select`) and `ops/slots.py` per Interfaces. `acquire` walks `table.waiting` in order with `used` = held slots: each waiter that fits is granted in the simulation (appended to `used`); when the granted waiter is the caller, move its entry to `held` and save.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_scheduler.py tests/test_ops_slots.py tests/test_ops_queue.py && make lint type`
Expected: PASS.

- [ ] **Step 5: Document and commit**

```bash
git add src/super_harness/scheduler.py src/super_harness/ops/slots.py tests/ docs/modules/
git commit -m "feat(ops): provider slots taken in arrival order"
```

---

### Task 4: Prompts and agent choice

**Files:**
- Create: `src/super_harness/ops/prompts.py`, `src/super_harness/ops/agents.py`
- Test: `tests/test_ops_prompts.py`, `tests/test_ops_agents.py`
- Docs: `docs/modules/ops/README.md`

**Interfaces:**
- Produces, `ops.prompts`:
  - `WORK_STEPS = ("plan", "implement", "docs")`, `REVIEW_STEPS = ("review_plan", "review_code", "security")`, `EDIT_STEPS = ("implement", "docs")`.
  - `INSTRUCTIONS: dict[str, str]`, exactly:
    - `plan`: "Write the implementation plan for this ticket: files, interfaces and tests. Do not edit files."
    - `review_plan`: "Review the plan in the Handoff against the Scope and Acceptance; fail only for real gaps."
    - `implement`: "Implement the ticket in this worktree, with tests. Do not commit; harness commits."
    - `review_code`: "Review the branch's changes against the Scope and Acceptance; read the diff with read-only git."
    - `security`: "Review the branch's changes for security problems; read the diff with read-only git."
    - `docs`: "Update the docs for the branch's changes. Do not commit; harness commits."
  - `output_kind(step: str) -> OutputKind` (`review` for `REVIEW_STEPS` and `run_tests`, else `work`); `profile(step: str) -> Profile` (`edit_worktree` for `EDIT_STEPS`, else `read_only`).
  - `new_prompt(ticket: Ticket, sections: Mapping[str, str], goal: str, *, role: str, step: str, diff_stat: str) -> str`
  - `resumed_prompt(ticket: Ticket, sections: Mapping[str, str], *, step: str, diff_stat: str) -> str`
  - `repair_prompt(problem: str) -> str` → `f"Your last reply failed: {problem}\nFix it and reply again with JSON that matches the schema."`
  - `handoff_text(handoff: str) -> str` (redacted, first 15 lines); `findings_text(findings: Sequence[Finding]) -> str` (one `- {severity} · {file or '-'}:{line} · {issue} · {fix}` line each, redacted); `log_line(at: datetime, step, role, provider, model, verdict, tokens: int) -> str` → `f"- {at:%Y-%m-%d %H:%M} · {step} · {role} · {provider}/{model or 'default'} · {verdict} · {tokens}"`.
  - `role_skill(paths: StorePaths, slug: str, skill: str) -> str | None`: `projects/<slug>/roles/<skill>.md`, then `defaults/roles/<skill>.md`; None until SP4 ships package roles.
- Produces, `ops.agents`:
  - `Pick(role: str, provider: str, model: str | None, fallback: bool)` (frozen dataclass); `provider` is `shell` for shell agents.
  - `pick(resolved: Settings, role: str, status: Callable[[str], ProviderStatus], *, skip: Collection[str] = ()) -> Pick`: the agent's `cli`, then each `fallback`, first usable and not in `skip`; `gemini` is never usable. None usable → `NeedsSetup`, message `f"{role} cannot run: {first problem}"` where a problem is `"gemini is not supported yet; pick another provider in SETTINGS.md"`, or `f"{provider} not installed; {hint}"` / `f"{provider} signed out; {hint}"`.
  - `detector(paths: StorePaths) -> Callable[[str], ProviderStatus]`: detects each provider once per call site (`functools.cache` around `adapters.get(name, runtime=paths.runtime).detect()`; `gemini` → not installed).

Prompt layout (empty sections and an empty diff stat are left out; sections come from the ticket, `goal` from the plan's `## Goal`):

```
new:      You are the {role} for ticket {id} "{title}", loop {loop} of {loop_max}, step {step}.
          {instruction}

          ## Goal (plan {plan})
          {goal}

          ## Scope / ## Acceptance / ## Handoff / ## Findings / ## Diff stat
          {...}

          Reply with JSON that matches the schema.
resumed:  Loop {loop}, step {step}: {instruction}

          ## Findings            (work steps)
          ## Handoff, ## Diff stat (review steps)
```

- [ ] **Step 1: Write the failing tests**

`tests/test_ops_prompts.py`:

```python
SECTIONS = {
    "Scope": "Retry webhooks.",
    "Acceptance": "- [ ] retries 3 times",
    "Handoff": "Plan: add retry.py",
    "Findings": "- low · a.py:1 · unclear name · rename",
    "Log": "- old",
}


def test_new_prompt_inlines_the_ticket(make_ticket: Make) -> None:
    ticket = make_ticket(loop=2, loop_max=3).meta
    text = prompts.new_prompt(
        ticket,
        SECTIONS,
        "Webhooks retry.",
        role="code-reviewer",
        step="review_code",
        diff_stat=" a.py | 2 +-",
    )
    assert (
        text.splitlines()[0]
        == 'You are the code-reviewer for ticket 7b55e0c1 "Rotate keys", loop 2 of 3, step review_code.'
    )
    assert text.splitlines()[1] == prompts.INSTRUCTIONS["review_code"]
    assert (
        "## Goal (plan a1b2c3d4)\nWebhooks retry." in text and "## Diff stat\n a.py | 2 +-" in text
    )
    assert "## Log" not in text and text.endswith("Reply with JSON that matches the schema.")


def test_resumed_prompts_carry_only_the_delta(make_ticket: Make) -> None:
    ticket = make_ticket(loop=2, loop_max=3).meta
    work = prompts.resumed_prompt(ticket, SECTIONS, step="implement", diff_stat="x")
    assert work.splitlines()[0] == f"Loop 2, step implement: {prompts.INSTRUCTIONS['implement']}"
    assert "## Findings" in work and "## Handoff" not in work and "## Scope" not in work
    review = prompts.resumed_prompt(ticket, SECTIONS, step="review_code", diff_stat=" a.py | 2 +-")
    assert "## Handoff" in review and "## Diff stat" in review and "## Findings" not in review


def test_sections_and_log_lines() -> None:
    assert prompts.handoff_text("\n".join(f"l{i}" for i in range(20))).splitlines()[-1] == "l14"
    finding = Finding(severity="high", file="", line=0, issue="token=abc123def456ghi789", fix="f")
    assert prompts.findings_text([finding]) == "- high · -:0 · token=[REDACTED] · f"
    at = datetime(2026, 10, 23, 9, 5, tzinfo=UTC)
    assert prompts.log_line(at, "plan", "planner", "claude", None, "pass", 1200) == (
        "- 2026-10-23 09:05 · plan · planner · claude/default · pass · 1200"
    )
    assert (prompts.output_kind("run_tests"), prompts.profile("implement")) == (
        "review",
        "edit_worktree",
    )
```

`tests/test_ops_agents.py`:

```python
def status(**usable: bool) -> Callable[[str], ProviderStatus]:
    def detect(name: str) -> ProviderStatus:
        ok = usable.get(name, True)
        return ProviderStatus(
            name=name, installed=ok, signed_in=ok, hint="" if ok else f"install {name}"
        )

    return detect


def test_pick_prefers_the_agent_then_its_fallbacks(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    resolved = settings.load(store_paths)
    assert agents.pick(resolved, "implementer", status()) == Pick(
        "implementer", "codex", None, False
    )
    assert agents.pick(resolved, "implementer", status(codex=False)) == Pick(
        "implementer", "claude", "sonnet", True
    )
    assert agents.pick(resolved, "implementer", status(), skip={"codex"}).provider == "claude"
    assert agents.pick(resolved, "test-runner", status()) == Pick(
        "test-runner", "shell", None, False
    )
    with pytest.raises(
        NeedsSetup, match="plan-reviewer cannot run: codex not installed; install codex"
    ):
        agents.pick(resolved, "plan-reviewer", status(codex=False))
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_ops_prompts.py tests/test_ops_agents.py`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement** both modules per Interfaces.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_ops_prompts.py tests/test_ops_agents.py && make lint type`
Expected: PASS.

- [ ] **Step 5: Document and commit**

```bash
git add src/super_harness/ops/ tests/test_ops_prompts.py tests/test_ops_agents.py docs/modules/ops/README.md
git commit -m "feat(ops): step prompts and agent choice with fallbacks"
```

---

### Task 5: The step loop

**Files:**
- Create: `src/super_harness/ops/lifecycle.py`, `src/super_harness/ops/steps.py`
- Modify: `src/super_harness/gitops.py` (add `commit_files`), `src/super_harness/ops/tickets.py` (rename `_refresh_queue` → `refresh_queue`), `tests/fakes/fake_cli.py` and `tests/conftest.py` (reply field `shell`; `engine` fixture; reply builders)
- Test: `tests/test_ops_steps.py`
- Docs: `docs/modules/ops/README.md`, `docs/modules/gitops/README.md`

**Interfaces:**
- Consumes: Tasks 2–4; `workflow.before/after/fingerprint`, `queue.progress_of`, `adapters.get`, `gitops`.
- Produces:
  - `gitops.commit_files(cwd: Path, sha: str) -> list[FileChange]` (numstat of one commit; `ticket_commits` uses it).
  - `ops.lifecycle.step_status(resolved: Settings, step: str) -> str` → `f"in_process/{resolved.status.names.get(step, step)}"`.
  - `ops.lifecycle.EVENT_TYPES: dict[str, str]`: sub-status → event type (`needs_approval`, `stalled`, `failed`, `awaiting_merge`, `paused` → `ticket.<same>`; `parked` → `ticket.moved`; `branch_ready` → `ticket.moved`).
  - `ops.lifecycle.status_event(slug: str, ticket: Ticket, before: str, reason: str) -> Event`: type from `EVENT_TYPES` of `ticket.sub_status`, fields `status`, `loop`, `loop_max`, `reason`, plus `from`/`to` for `ticket.moved`.
  - `ops.steps.JobEnd(status: str, reason: str)` (dataclass).
  - `ops.steps.run_job(ticket_id: str, *, project: str | None = None, steps: int | None = None) -> JobEnd`: runs steps until a gate, the end, a flag or the budget (SP3 spec §5); `steps=N` stops after N steps at `in_process/paused` "step budget spent".
  - `ops.steps.fail_ticket(paths: StorePaths, slug: str, ticket_id: str, reason: str) -> None`: under the project lock, an `in_process` ticket that is not at a gate → `in_process/failed` with `reason`, slots released, `ticket.failed` journaled, store committed.
  - Test support: fake reply field `shell` (a command the fake runs with `sh -c` in its working directory after applying `edits` and before replying); `FakeClis.claude_output(structured: dict) -> str` and `FakeClis.codex_output(structured: dict) -> str` (the recorded fixtures with their output replaced); fixture `engine -> Engine(paths, repo, slug, ticket_id)` with `ticket() -> Doc[Ticket]`, `state() -> TicketState`, `worktree: Path`. `engine` registers the repo, saves plan `a1b2c3d4` (Goal "Webhook deliveries retry with backoff."), saves ticket `7b55e0c1` (`importance: simple`, `workflow: simple`, `loop_max: 3`, `status: in_process/under_planning`, `step: plan`, `branch: hrn/7b55e0c1`, Scope and Acceptance), creates its worktree with `gitops.ensure_worktree`, and sets `GIT_CONFIG_GLOBAL` to a temp file with a user identity.

`run_job` per step, in order (SP3 spec §5, system spec §7.1):

1. Under the project lock: reload the ticket and its `TicketState`. Stop with `JobEnd` when the ticket is not `in_process` or is at a gate. A park request → `in_queue/parked` (step kept, flag cleared); a pause covering the project, or a spent budget → `in_process/paused`. Then `workflow.before(resolved, progress)` with `progress_of` plus the state's streaks and plan rounds: `Halt` → set the status (and `state.approval`), journal `status_event`, stop; `Merge` → Task 9 wires it, until then `in_process/awaiting_merge`; `Run(step)` → `ticket.step = step`, status `step_status`, save, `set_worker_step`.
2. `agents.pick` for the step's role with `detector(paths)`; `NeedsSetup` → `fail_ticket` with its message.
3. Not `shell`: `slots.acquire` with `pid=os.getpid()`; while false, status `in_process/waiting_slot`, `runtime.beat`, sleep 5 s (module constant `SLOT_POLL_S`), then restore the step status.
4. Session: reuse `ticket.sessions[role]` when `sessions.reuse` and its provider is the pick's; otherwise a new session (claude: a `uuid4` stored in `ticket.sessions` before the call). Journal `step.start` and `session.created` or `session.resumed`. Record `state.running` and bump `state.calls`; the log is `logs/<id>-<calls>.out`.
5. Build the `StepRequest`: `new_prompt` or `resumed_prompt`; the role skill (`role_skill`) on new sessions; `output_kind`, `profile`, `timeout_s = step_timeout_min * 60`, the project's test and lint commands, provider options, `bypass_permissions`, and `state.totals[role]` as `prior_usage` when resuming. Review steps get `gitops.diff(worktree, base, stat=True)`. Before an editing step, `state.start_commit = gitops.head(worktree)`. Call the adapter (Task 6 adds the error handling; here an error → `fail_ticket(f"{error}: {detail}; log: {log}")`).
6. After an editing step: `reset_soft(start)` when `head` moved, then `commit_all` with subject `f"hrn({id}): loop {loop} {step}: {first line of summary}"` and trailers `Harness-Ticket` (uuid), `Harness-Step`, `Harness-Loop`, `Harness-Agent` (role), `Harness-Model` (`provider/model or default`).
7. Under the project lock: reload; work steps replace `## Handoff` with `handoff_text`; review steps replace `## Findings` with `findings_text` (empty on a pass); append `log_line` to `## Log`; add `result.usage.tokens` to `ticket.tokens`; store the session (`result.session_id` wins) and `total_usage`; clear `state.running`; journal `step.end` (system spec §6.1 fields plus `fingerprints`); route with `workflow.after` (`Outcome(verdict, fingerprints)`; work steps pass); apply the decision as in item 1; `slots.release`; journal and commit the store (`records.record`). `Run` → next step.

- [ ] **Step 1: Write the failing tests** in `tests/test_ops_steps.py`

```python
REVIEW_FAIL = {
    "verdict": "fail",
    "summary": "Missing jitter.",
    "findings": [
        {
            "severity": "medium",
            "file": "retry.py",
            "line": 3,
            "issue": "no jitter",
            "fix": "add jitter",
        }
    ],
}
REVIEW_PASS = {"verdict": "pass", "summary": "Good.", "findings": []}


def test_one_step_writes_handoff_log_tokens_and_session(
    engine: Engine, fake_clis: FakeClis, journal_events: Events
) -> None:
    raw = fake_clis.fixture_json("claude/work_resume.json")
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    end = steps.run_job("7b55e0c1", steps=1)
    assert end == JobEnd("in_process/paused", "step budget spent")
    doc = engine.ticket()
    assert (
        doc.meta.step == "implement"
        and doc.meta.tokens == raw["usage"]["input_tokens"] + raw["usage"]["output_tokens"]
    )
    assert doc.sections["Handoff"] == raw["structured_output"]["handoff"]
    assert (
        doc.sections["Log"]
        .splitlines()[-1]
        .endswith(f"· plan · planner · claude/opus · pass · {doc.meta.tokens}")
    )
    assert doc.meta.sessions["planner"].id == raw["session_id"]
    [call] = fake_clis.calls("claude")
    assert (
        "--session-id" in call["argv"] and Path(call["cwd"]).resolve() == engine.worktree.resolve()
    )
    types = [e["type"] for e in journal_events()]
    assert types[-4:] == ["step.start", "session.created", "step.end", "ticket.paused"]


def test_a_full_simple_workflow(
    engine: Engine, fake_clis: FakeClis, run_git: Callable[..., str]
) -> None:
    fake_clis.queue("claude", fixture="claude/work_resume.json")  # plan
    fake_clis.queue(
        "codex", fixture="codex/work_resume.jsonl", edits={"retry.py": "retries = 3\n"}
    )  # implement
    fake_clis.queue("claude", stdout=fake_clis.claude_output(REVIEW_FAIL))  # review fails
    fake_clis.queue(
        "codex",
        fixture="codex/work_resume.jsonl",
        edits={"retry.py": "retries = 3\njitter = True\n"},
    )
    fake_clis.queue("claude", stdout=fake_clis.claude_output(REVIEW_PASS))  # review passes
    end = steps.run_job("7b55e0c1")
    assert end == JobEnd("in_process/awaiting_merge", "every step passed")
    doc = engine.ticket()
    assert (doc.meta.loop, doc.meta.step, doc.sections["Findings"]) == (2, None, "")
    log = run_git(engine.worktree, "log", "--format=%s%n%(trailers:only,unfold)", "main..HEAD")
    assert "hrn(7b55e0c1): loop 2 implement: Added retry with backoff." in log
    assert f"Harness-Ticket: {doc.meta.uuid}" in log and "Harness-Model: codex/default" in log
    reviews = [c["argv"] for c in fake_clis.calls("claude")][1:]
    assert (
        "--session-id" in reviews[0]
        and reviews[1][reviews[1].index("--resume") + 1] == doc.meta.sessions["code-reviewer"].id
    )
    assert fake_clis.calls("codex")[1]["argv"][:2] == ["exec", "resume"]


def test_a_failing_review_writes_findings_and_recirculates(
    engine: Engine, fake_clis: FakeClis
) -> None:
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"retry.py": "retries = 3\n"})
    fake_clis.queue("claude", stdout=fake_clis.claude_output(REVIEW_FAIL))
    steps.run_job("7b55e0c1", steps=3)
    doc = engine.ticket()
    assert (doc.meta.loop, doc.meta.step) == (2, "implement")
    assert doc.sections["Findings"] == "- medium · retry.py:3 · no jitter · add jitter"
    assert engine.state().streaks == {"review_code": {fingerprint("retry.py", "no jitter"): 1}}


def test_an_agent_commit_is_folded_into_the_harness_commit(
    engine: Engine, fake_clis: FakeClis, run_git: Callable[..., str]
) -> None:
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue(
        "codex",
        fixture="codex/work_resume.jsonl",
        edits={"retry.py": "retries = 3\n"},
        shell="git add -A && git commit -qm 'agent commit'",
    )
    steps.run_job("7b55e0c1", steps=2)
    subjects = run_git(engine.worktree, "log", "--format=%s", "main..HEAD").splitlines()
    assert subjects == ["hrn(7b55e0c1): loop 1 implement: Added retry with backoff."]
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_ops_steps.py`
Expected: FAIL with `ImportError` (`super_harness.ops.steps`).

- [ ] **Step 3: Implement** `gitops.commit_files`, the `refresh_queue` rename, the fake's `shell` field and the test support, then `ops/lifecycle.py` and `ops/steps.py` per Interfaces and the numbered list.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_ops_steps.py tests/test_gitops.py tests/test_ops_tickets.py && make lint type`
Expected: PASS.

- [ ] **Step 5: Document and commit**

```bash
git add src/super_harness/ tests/ docs/modules/
git commit -m "feat(ops): step loop runs a ticket through its workflow"
```

---

### Task 6: Step errors, retries, fallback, quota and flags

**Files:**
- Modify: `src/super_harness/ops/steps.py`
- Test: `tests/test_ops_steps.py`
- Docs: `docs/modules/ops/README.md`

**Interfaces:**
- Consumes: Task 5.
- Produces (behaviour of `run_job`; module constants `QUOTA_WAIT_S = 900`, `SLOT_POLL_S = 5`, `sleep = time.sleep`, and `step_timeout(resolved: Settings) -> int` returning `step_timeout_min * 60`; tests replace the last two):
  - `timeout` → the same request once more; a second `timeout` → `failed` `f"timeout: killed after {s} s twice; log: {log}"`.
  - `schema` → once more as a resumed turn with `repair_prompt(detail)` when the result named a session, else the same request; a second → `failed` `f"schema: {detail}; log: {log}"`.
  - `rate_limit` → with `fallback_on_rate_limit`, `agents.pick(..., skip={provider})` and a new session on the fallback; otherwise (or with no fallback) `in_process/waiting_quota` until `retry_after` (else `QUOTA_WAIT_S`), beating, then the same request again.
  - `auth` → `failed` `f"sign in to {binary} interactively"` (`binary`: `claude`, `codex`, `agy`).
  - `empty`, `crash` → `failed` `f"{error}: {detail}; log: {log}"`.
  - Every attempt's usage counts toward `ticket.tokens`.
  - A `CommitFailed` after an editing step → one repair turn on the step's session with `repair_prompt(f"the commit hook failed:\n{last 20 lines of output}")`, then `commit_all` again; a second failure → `failed` `f"commit failed: {last line of output}"`.
  - Before writing results (item 7 of Task 5): a ticket that is no longer `in_process`, or whose `step` changed, keeps its state; the result is dropped, the slot released, and `run_job` returns `JobEnd(<its status>, "changed while the step ran")`.
  - Job start: a `state.running` left by a dead worker whose role has no session → `adapters.get(provider).recover_session(log)` fills `ticket.sessions[role]`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_ops_steps.py`)

```python
def test_a_timeout_retries_once_then_fails(
    engine: Engine, fake_clis: FakeClis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(steps, "step_timeout", lambda resolved: 1)
    fake_clis.queue("claude", fixture="claude/work_resume.json", sleep=3)
    fake_clis.queue("claude", fixture="claude/work_resume.json", sleep=3)
    end = steps.run_job("7b55e0c1")
    assert end.status == "in_process/failed" and end.reason.startswith(
        "timeout: killed after 1 s twice; log: "
    )
    assert len(fake_clis.calls("claude")) == 2


def test_schema_errors_get_one_repair_turn(engine: Engine, fake_clis: FakeClis) -> None:
    bad = fake_clis.claude_output({"summary": "s"})  # handoff missing
    fake_clis.queue("claude", stdout=bad)
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    steps.run_job("7b55e0c1", steps=1)
    second = fake_clis.calls("claude")[1]["argv"]
    assert "--resume" in second and second[2].startswith(
        "Your last reply failed: output does not match the work schema"
    )
    assert engine.ticket().meta.step == "implement"


def test_rate_limits_fall_back_then_wait(
    engine: Engine, fake_clis: FakeClis, monkeypatch: pytest.MonkeyPatch
) -> None:
    naps: list[float] = []
    monkeypatch.setattr(steps, "sleep", naps.append)
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue("codex", fixture="codex/usage_limit.jsonl")  # implementer on codex
    fake_clis.queue("claude", fixture="claude/work_resume.json")  # fallback claude/sonnet
    steps.run_job("7b55e0c1", steps=2)
    fallback = fake_clis.calls("claude")[1]["argv"]
    assert fallback[fallback.index("--model") + 1] == "sonnet" and naps == []
    assert engine.ticket().meta.sessions["implementer"].provider == "claude"


def test_quota_waits_without_a_fallback(
    engine: Engine, fake_clis: FakeClis, store_paths: StorePaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    naps: list[float] = []
    monkeypatch.setattr(steps, "sleep", naps.append)
    write_settings(store_paths, "fallback_on_rate_limit: false\n")
    fake_clis.queue("claude", fixture="claude/usage_limit.json")
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    steps.run_job("7b55e0c1", steps=1)
    assert naps and engine.ticket().meta.step == "implement"


def test_auth_and_crash_fail_the_ticket(engine: Engine, fake_clis: FakeClis) -> None:
    fake_clis.queue("claude", fixture="claude/auth_error.json")
    assert steps.run_job("7b55e0c1") == JobEnd(
        "in_process/failed", "sign in to claude interactively"
    )


def test_a_failing_hook_gets_one_repair_turn(engine: Engine, fake_clis: FakeClis) -> None:
    hook = engine.repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\ntest -f fixed || { echo 'lint: add fixed'; exit 1; }\n")
    hook.chmod(0o755)
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"retry.py": "x = 1\n"})
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"fixed": "yes\n"})
    steps.run_job("7b55e0c1", steps=2)
    repair = fake_clis.calls("codex")[1]["argv"]
    assert "lint: add fixed" in repair[-1] and engine.ticket().meta.step == "review_code"


def test_a_ticket_moved_during_its_step_keeps_the_users_status(
    engine: Engine, fake_clis: FakeClis
) -> None:
    move = "harness ticket move 7b55e0c1 done --why 'user closed it' --by user"
    fake_clis.queue("claude", fixture="claude/work_resume.json", shell=move)
    end = steps.run_job("7b55e0c1")
    assert end == JobEnd("done/closed", "changed while the step ran")
    assert (
        engine.ticket().meta.status == "done/closed" and runtime.load_slots(engine.paths).held == []
    )


def test_park_and_pause_flags_stop_before_the_next_step(
    engine: Engine, fake_clis: FakeClis
) -> None:
    runtime.set_park(engine.paths, "7b55e0c1", on=True)
    assert steps.run_job("7b55e0c1").status == "in_queue/parked"
    assert engine.ticket().meta.step == "plan" and not runtime.park_requested(
        engine.paths, "7b55e0c1"
    )
```

The moved-ticket test needs `harness` on the fake's `PATH` (the venv bin is there) and `HARNESS_HOME` (set by `store_paths`); the fake runs `shell` before replying, so the move lands mid-step.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_ops_steps.py`
Expected: the new tests FAIL (the Task 5 behaviour fails the ticket on the first error).

- [ ] **Step 3: Implement** the behaviour in Interfaces inside `ops/steps.py`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_ops_steps.py && make lint type`
Expected: PASS.

- [ ] **Step 5: Document and commit**

```bash
git add src/super_harness/ops/steps.py tests/test_ops_steps.py docs/modules/ops/README.md
git commit -m "feat(ops): step retries, fallbacks, quota waits, hook repair and user moves"
```

---

### Task 7: Controls: run, approve, park, stop, pause, resume

**Files:**
- Create: `src/super_harness/ops/controls.py`
- Modify: `src/super_harness/cli.py`
- Test: `tests/test_ops_controls.py`, `tests/test_cli_controls.py`
- Docs: `docs/modules/ops/README.md`, `docs/modules/cli/README.md`

**Interfaces:**
- Consumes: Tasks 2–6; `scheduler.overlaps`, `gitops.ensure_worktree`, `steps.fail_ticket`.
- Produces:
  - `Started(id, project, step, provider)`; `RunResult(started: list[Started], skipped: dict[str, str])`.
  - `run_tickets(ids: Sequence[str], *, steps: int | None = None, project: str | None = None, by: str) -> RunResult`: `CODEX_SANDBOX_NETWORK_DISABLED=1` → `NeedsSetup("harness run cannot start workers inside a network-less codex sandbox; run it outside the sandbox")`. Per id, the first failing check names the skip reason: a live worker record → `"already running"`; status not `in_queue/ready` or `in_process/{failed,stalled,paused}` → `f"status {status}"`; paused scope → `"paused"`; overlap with another `in_process` ticket of the project → `f"touches overlap {id}"`; `workflow.before` halts other than at `approve` → its reason; `agents.pick` raises → its message (a setup skip); no slot by `scheduler.fits` over `slots.occupied(exclude=id)` → `f"no free {provider} slot"`; `ensure_worktree` fails → its message. A claim then, under the project lock: `ensure_worktree` under `repo-<slug>.lock` (path `paths.worktree(slug, id)`, branch `hrn/<id>`, base from the registry), `ticket.branch`, `ticket.step`, status `step_status`; resuming a stalled ticket clears `state.streaks`; `slots.queue_slot` for a provider step; `spawn_worker`; `save_worker`; `claims.last[slug] = now`; journal `ticket.claimed` (`from`, `step`, `provider`, `by`). One store commit at the end. No ticket started and some skip was a setup skip → `NeedsSetup` with that message.
  - `spawn_worker(paths: StorePaths, slug: str, ticket_id: str, steps: int | None) -> int`: `subprocess.Popen([sys.executable, "-m", "super_harness.worker", "ticket", ticket_id, *(["--steps", str(steps)] if steps else []), "--project", slug], start_new_session=True, stdin=DEVNULL, stdout=<runtime/logs/<id>.log, append>, stderr=STDOUT, env=os.environ)`; returns the pid.
  - `Approved(id, project, status)`; `approve_ticket(ticket_id, *, loops: int | None, tokens: int | None, project, by) -> Approved`: needs `in_process/needs_approval` with `state.approval`, else `UserError(f"{id} is not waiting for approval")`; `workflow.approve` → `Run` restarts the worker (as a claim without the checks), `Halt` sets that status, `Merge` → `in_process/awaiting_merge` until Task 9; writes `loop_max`/`tokens_max` grants; journal `ticket.approved` (`approval`, `loops`, `tokens`, `by`).
  - `Parked(id, project, deferred: bool)`; `park_ticket(ticket_id, why, *, project, by) -> Parked`: a live worker → `set_park` (deferred); otherwise status `in_queue/parked` with step kept, journal `ticket.moved`.
  - `stop_ticket(ticket_id, *, project, by) -> str`: SIGTERM to the worker's process group, wait up to 10 s (module constant `STOP_GRACE_S`) for its pid to go, SIGKILL the group, then `fail_ticket(..., "stopped")` (event type `ticket.stopped` instead of `ticket.failed`), `drop_worker`; no worker → `UserError(f"{id} has no running worker")`.
  - `Paused(project: str | None, running: int)`; `pause(project: str | None, *, by) -> Paused` (`set_pause` on; `running` counts live workers in scope; journal `ticket.paused` per running ticket is the worker's job).
  - `Resumed(started: list[str])`; `resume(project: str | None, *, by) -> Resumed`: `set_pause` off, then `run_tickets` for the scope's `in_process/paused` tickets.
- CLI (each with `--json`, `--project`/`-p`, `--by`): `run ID... [--steps N]` → `started <id> <step>→<provider>` / `skipped <id>: <reason>` lines, capped, exit 1 when none started; `approve ID [--loops N] [--tokens N]` → `ticket <id> approved; running` (or `ticket <id> approved; <status>` when it halts); `park ID --why W` → `ticket <id> → in_queue/parked` (+ ` after its step` when deferred); `stop ID` → `ticket <id> stopped`; `pause` → `paused: N running finish their step`; `resume` → `resumed N`.

- [ ] **Step 1: Write the failing tests**

`tests/test_ops_controls.py` (replace `controls.spawn_worker` with a recorder so no process starts):

```python
@pytest.fixture
def spawned(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int | None]]:
    calls: list[tuple[str, int | None]] = []

    def spawn(paths: StorePaths, slug: str, ticket_id: str, steps: int | None) -> int:
        calls.append((ticket_id, steps))
        return os.getpid()  # a live pid, as a real worker's would be

    monkeypatch.setattr(controls, "spawn_worker", spawn)
    return calls


def test_run_claims_a_ready_ticket(
    registered_repo: Path,
    store_paths: StorePaths,
    make_ticket: Make,
    spawned: list[tuple[str, int | None]],
    journal_events: Events,
) -> None:
    project = store_paths.project("payments-api")
    documents.save_ticket(project, make_ticket(importance="simple", workflow="simple", loop_max=3))
    result = controls.run_tickets(["7b55e0c1"], steps=2, by="claude")
    assert result.started == [
        Started("7b55e0c1", "payments-api", "plan", "claude")
    ] and spawned == [("7b55e0c1", 2)]
    doc = documents.load_ticket(documents.find_ticket(project, "7b55e0c1"))
    assert (doc.meta.status, doc.meta.step, doc.meta.branch) == (
        "in_process/under_planning",
        "plan",
        "hrn/7b55e0c1",
    )
    assert store_paths.worktree("payments-api", "7b55e0c1").is_dir()
    assert runtime.load_worker(store_paths, "7b55e0c1").pid == os.getpid()
    assert [e.ticket for e in runtime.load_slots(store_paths).waiting] == ["7b55e0c1"]
    assert journal_events()[-1]["type"] == "ticket.claimed"


def test_run_skips_with_reasons(
    registered_repo: Path,
    store_paths: StorePaths,
    make_ticket: Make,
    spawned: list[tuple[str, int | None]],
) -> None:
    project = store_paths.project("payments-api")
    documents.save_ticket(project, make_ticket(importance="simple", workflow="simple", loop_max=3))
    documents.save_ticket(
        project, make_ticket("a91b3d07", importance="simple", workflow="simple", loop_max=3)
    )
    documents.save_ticket(project, make_ticket("3c9d0e11", status="in_queue/parked"))
    result = controls.run_tickets(["7b55e0c1", "a91b3d07", "3c9d0e11"], by="claude")
    assert [s.id for s in result.started] == ["7b55e0c1"]
    assert result.skipped == {
        "a91b3d07": "touches overlap 7b55e0c1",
        "3c9d0e11": "status in_queue/parked",
    }
    again = controls.run_tickets(["7b55e0c1"], by="claude")
    assert again.skipped == {"7b55e0c1": "already running"} and len(spawned) == 1


def test_run_needs_a_usable_provider_and_no_sandbox(
    registered_repo: Path,
    store_paths: StorePaths,
    make_ticket: Make,
    fake_clis: FakeClis,
    monkeypatch: pytest.MonkeyPatch,
    spawned: list[tuple[str, int | None]],
) -> None:
    documents.save_ticket(
        store_paths.project("payments-api"),
        make_ticket(importance="simple", workflow="simple", loop_max=3),
    )
    fake_clis.sign_out("claude")
    with pytest.raises(NeedsSetup, match="planner cannot run: claude signed out"):
        controls.run_tickets(["7b55e0c1"], by="claude")
    monkeypatch.setenv("CODEX_SANDBOX_NETWORK_DISABLED", "1")
    with pytest.raises(NeedsSetup, match="network-less codex sandbox"):
        controls.run_tickets(["7b55e0c1"], by="codex")


def test_approve_grants_loops_and_restarts(
    engine: Engine, spawned: list[tuple[str, int | None]]
) -> None:
    doc = engine.ticket()
    doc.meta.status, doc.meta.step, doc.meta.loop = "in_process/needs_approval", "implement", 3
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    runtime.save_ticket_state(engine.paths, "7b55e0c1", TicketState(approval="loop_cap"))
    approved = controls.approve_ticket("7b55e0c1", loops=2, tokens=None, project=None, by="user")
    assert approved.status == "in_process/under_implementation" and spawned == [("7b55e0c1", None)]
    assert (engine.ticket().meta.loop, engine.ticket().meta.loop_max) == (4, 5)
    with pytest.raises(UserError, match="7b55e0c1 is not waiting for approval"):
        controls.approve_ticket("7b55e0c1", loops=None, tokens=None, project=None, by="user")


def test_park_defers_while_a_worker_runs(engine: Engine) -> None:
    runtime.save_worker(
        engine.paths, WorkerRecord(id="7b55e0c1", project=engine.slug, pid=os.getpid())
    )
    assert controls.park_ticket("7b55e0c1", "later", project=None, by="user").deferred
    assert runtime.park_requested(engine.paths, "7b55e0c1")
    runtime.drop_worker(engine.paths, "7b55e0c1")
    assert not controls.park_ticket("7b55e0c1", "later", project=None, by="user").deferred
    assert engine.ticket().meta.status == "in_queue/parked"


def test_pause_and_resume(engine: Engine, spawned: list[tuple[str, int | None]]) -> None:
    assert controls.pause("payments-api", by="user") == Paused("payments-api", 0)
    doc = engine.ticket()
    doc.meta.status = "in_process/paused"
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    assert controls.resume("payments-api", by="user") == Resumed(["7b55e0c1"])
    assert not runtime.pause_state(engine.paths).covers("payments-api")
```

`tests/test_cli_controls.py` checks the formatting with the same `spawned` fixture: `run` prints `started 7b55e0c1 plan→claude`; a second `run` prints `skipped 7b55e0c1: already running` and exits 1; `park` prints `ticket 7b55e0c1 → in_queue/parked`; `pause` prints `paused: 0 running finish their step`.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_ops_controls.py tests/test_cli_controls.py`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement** `ops/controls.py` and the CLI commands per Interfaces. A worker is live when its record exists, its heartbeat is under `lifecycle.DEAD_AFTER_S = 120` seconds old, and `lifecycle.pid_alive(pid)` holds: `os.waitpid(pid, os.WNOHANG)` first reaps it when it is this process's child (ignore `ChildProcessError`), then `os.kill(pid, 0)` (`PermissionError` counts as alive). Add both to `ops/lifecycle.py`; `stop_ticket` and Task 10 use them.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_ops_controls.py tests/test_cli_controls.py && make lint type`
Expected: PASS.

- [ ] **Step 5: Document and commit**

```bash
git add src/super_harness/ tests/test_ops_controls.py tests/test_cli_controls.py docs/modules/
git commit -m "feat(ops): run claims tickets; approve, park, stop, pause and resume"
```

---

### Task 8: The worker process

**Files:**
- Create: `src/super_harness/worker/__init__.py`, `src/super_harness/worker/__main__.py`
- Modify: `src/super_harness/adapters/process.py` (end the CLI's group when the caller is interrupted), `pyproject.toml` (layers contract)
- Test: `tests/test_worker.py`, `tests/test_adapters_core.py`
- Docs: `docs/modules/worker/README.md` (new), `docs/modules/adapters/README.md`, `docs/architecture.md`

**Interfaces:**
- Consumes: `ops.steps.run_job`, `ops.steps.fail_ticket`, `store` only through `ops` (add `ops.steps.heartbeat(ticket_id)` and `ops.steps.forget_worker(ticket_id)` wrappers so `worker` never imports `store`).
- Produces:
  - `python -m super_harness.worker ticket <id> [--steps N] [--project SLUG]`: starts a daemon thread calling `steps.heartbeat(id)` every `HEARTBEAT_S = 15` seconds, installs a SIGTERM handler that raises `SystemExit(143)`, runs `run_job`, and in `finally` stops the thread and calls `forget_worker`. An unexpected exception → `fail_ticket(..., f"worker error: {exc}; log: runtime/logs/<id>.log")`, traceback to stderr (the log), exit 1.
  - `run_process`: when waiting is interrupted by any exception, the CLI's group is ended with `min(grace_s, 3.0)` before the exception propagates.
  - Layers contract becomes `cli | worker > ops > memory > journal | settings > store > model`, and a forbidden contract keeps `worker` from importing `store`, `settings`, `memory` and `journal`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_adapters_core.py`:

```python
def test_an_interrupted_wait_ends_the_cli_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_file = tmp_path / "cli.pid"

    def interrupt(signum: int, frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGALRM, interrupt)
    signal.alarm(1)
    with pytest.raises(KeyboardInterrupt):
        run_process(
            ["sh", "-c", f"echo $$ > {pid_file}; sleep 30"],
            cwd=tmp_path,
            env=dict(os.environ),
            timeout_s=30,
            log=tmp_path / "i.out",
        )
    assert _gone(int(pid_file.read_text()))
```

`tests/test_worker.py` (real detached processes; `engine` from Task 5):

```python
def wait_until(check: Callable[[], bool], within: float = 20.0) -> None:
    deadline = time.monotonic() + within
    while not check():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.1)


def test_a_detached_worker_runs_its_steps(engine: Engine, fake_clis: FakeClis) -> None:
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    pid = controls.spawn_worker(engine.paths, engine.slug, "7b55e0c1", 1)
    runtime.save_worker(engine.paths, WorkerRecord(id="7b55e0c1", project=engine.slug, pid=pid))
    wait_until(lambda: engine.ticket().meta.status == "in_process/paused")
    wait_until(lambda: runtime.load_worker(engine.paths, "7b55e0c1") is None)
    assert engine.ticket().meta.step == "implement"


def test_stop_ends_the_worker_and_its_cli(engine: Engine, fake_clis: FakeClis) -> None:
    fake_clis.queue("claude", fixture="claude/work_resume.json", sleep=60)
    pid = controls.spawn_worker(engine.paths, engine.slug, "7b55e0c1", None)
    runtime.save_worker(engine.paths, WorkerRecord(id="7b55e0c1", project=engine.slug, pid=pid))
    wait_until(lambda: len(fake_clis.calls("claude")) == 1)
    started = time.monotonic()
    assert controls.stop_ticket("7b55e0c1", project=None, by="user") == "in_process/failed"
    assert time.monotonic() - started < 12
    assert engine.ticket().meta.status == "in_process/failed"
    assert runtime.load_slots(engine.paths).held == []
    assert (
        subprocess.run(["pgrep", "-f", "fake_cli.py claude"], capture_output=True).returncode == 1
    )
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_worker.py tests/test_adapters_core.py`
Expected: FAIL (`No module named super_harness.worker`; the interrupt test leaves `sleep` running).

- [ ] **Step 3: Implement** the `run_process` change, the worker package, the two `ops.steps` wrappers and the import contracts.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_worker.py tests/test_adapters_core.py && make lint type`
Expected: PASS; lint-imports keeps every contract.

- [ ] **Step 5: Document and commit** (worker README: job line, heartbeat, signals, exit codes; architecture `worker` row and the layers line)

```bash
git add src/super_harness/ tests/ pyproject.toml docs/
git commit -m "feat(worker): detached worker with heartbeat and clean stop"
```

---

### Task 9: Merge

**Files:**
- Create: `src/super_harness/ops/merging.py`
- Modify: `src/super_harness/ops/steps.py` (`Merge` decision), `src/super_harness/ops/controls.py` (`Merge` after approve), `src/super_harness/cli.py`
- Test: `tests/test_ops_merging.py`
- Docs: `docs/modules/ops/README.md`, `docs/modules/cli/README.md`

**Interfaces:**
- Consumes: `gitops.rebase`, `merge_ff`, `remove_worktree`, `is_clean`, `current_branch`; `tickets.refresh_queue`; `lifecycle`.
- Produces:
  - `Merged(id, project, commits: int, base: str)`; `merge_ticket(ticket_id, *, project, by) -> Merged`: needs `in_process/awaiting_merge` or `done/branch_ready`, else `UserError(f"{id} is {status}; merge needs awaiting_merge or branch_ready")`. Under the project lock and `repo-<slug>.lock`: `rebase(worktree, base)`; conflicts → `## Findings` gets `- high · {files joined by ', '}:0 · rebase onto {base} conflicts · resolve the conflict in implement`, and the ticket goes to `in_queue/ready` at `implement` with loop + 1 (at `loop_max`: `in_process/needs_approval`, `state.approval = "loop_cap"`), journal `ticket.recirculated`, then `UserError(f"conflict in {files}; {id} sent back to implement (loop {n})")`. Otherwise `merge_ff(repo, branch, base)` (its `GitError` propagates, exit 1), `remove_worktree`, status `done/merged`, `step` cleared, `refresh_queue`, `drop_ticket_state`, journal `ticket.merged` (`status`, `loop`, `loop_max`, `reason: f"{n} commits into {base}"`, `commits`, `by`) plus `ticket.moved` for each dependent turned ready.
  - `merge_if_clean(paths, slug, ticket_id, *, by) -> str`: the `Merge` decision: when the main working tree is clean and on the base branch, `merge_ticket` and return `done/merged`; otherwise `in_process/awaiting_merge` with reason `"main working tree is not clean or not on <base>"`. `run_job` and `approve_ticket` call it.
- CLI: `merge ID` → `merged <id>: N commits into <base>`.

- [ ] **Step 1: Write the failing tests** in `tests/test_ops_merging.py`

```python
def ready_to_merge(engine: Engine, run_git: Callable[..., str]) -> None:
    (engine.worktree / "retry.py").write_text("retries = 3\n")
    gitops.commit_all(
        engine.worktree,
        "hrn(7b55e0c1): loop 1 implement: retry",
        {"Harness-Ticket": str(engine.ticket().meta.uuid)},
    )
    doc = engine.ticket()
    doc.meta.status, doc.meta.step = "in_process/awaiting_merge", None
    documents.save_ticket(engine.paths.project(engine.slug), doc)


def test_merge_fast_forwards_and_unblocks_dependents(
    engine: Engine, make_ticket: Make, run_git: Callable[..., str]
) -> None:
    ready_to_merge(engine, run_git)
    dependent = make_ticket("a91b3d07", status="in_queue/blocked", depends_on=["7b55e0c1"])
    documents.save_ticket(engine.paths.project(engine.slug), dependent)
    assert merging.merge_ticket("7b55e0c1", project=None, by="user") == Merged(
        "7b55e0c1", "payments-api", 1, "main"
    )
    assert engine.ticket().meta.status == "done/merged" and not engine.worktree.exists()
    assert (engine.repo / "retry.py").exists()
    assert (
        records.load_ticket(
            documents.find_ticket(engine.paths.project(engine.slug), "a91b3d07")
        ).meta.status
        == "in_queue/ready"
    )


def test_a_conflict_sends_the_ticket_back(engine: Engine, run_git: Callable[..., str]) -> None:
    (engine.worktree / "README.md").write_text("ticket\n")
    gitops.commit_all(engine.worktree, "edit readme", {})
    (engine.repo / "README.md").write_text("main\n")
    gitops.commit_all(engine.repo, "main edit", {})
    doc = engine.ticket()
    doc.meta.status, doc.meta.step = "in_process/awaiting_merge", None
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    with pytest.raises(
        UserError, match=r"conflict in README.md; 7b55e0c1 sent back to implement \(loop 2\)"
    ):
        merging.merge_ticket("7b55e0c1", project=None, by="user")
    after = engine.ticket()
    assert (after.meta.status, after.meta.step, after.meta.loop) == (
        "in_queue/ready",
        "implement",
        2,
    )
    assert "README.md:0 · rebase onto main conflicts" in after.sections["Findings"]


def test_merge_refuses_other_states_and_a_dirty_tree(
    engine: Engine, run_git: Callable[..., str]
) -> None:
    with pytest.raises(UserError, match="merge needs awaiting_merge or branch_ready"):
        merging.merge_ticket("7b55e0c1", project=None, by="user")
    ready_to_merge(engine, run_git)
    (engine.repo / "README.md").write_text("dirty\n")
    with pytest.raises(UserError, match="main working tree has uncommitted changes"):
        merging.merge_ticket("7b55e0c1", project=None, by="user")
    assert (
        merging.merge_if_clean(engine.paths, engine.slug, "7b55e0c1", by="harness")
        == "in_process/awaiting_merge"
    )
```

Add one test to `tests/test_ops_steps.py`: with `merge.mode: auto` (via `write_settings`), the full simple workflow of Task 5 ends `JobEnd("done/merged", ...)`.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_ops_merging.py tests/test_ops_steps.py`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement** `ops/merging.py`, the two `Merge` call sites and the CLI command.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_ops_merging.py tests/test_ops_steps.py && make lint type`
Expected: PASS.

- [ ] **Step 5: Document and commit**

```bash
git add src/super_harness/ tests/ docs/modules/
git commit -m "feat(ops): merge rebases, fast-forwards and cleans up"
```

---

### Task 10: wait, the dead-worker check and conductor pings

**Files:**
- Create: `src/super_harness/ops/waiting.py`
- Modify: `src/super_harness/ops/queue.py` (`next_tickets` runs the check and pings), `src/super_harness/ops/projects.py` (doctor reports dead workers), `src/super_harness/cli.py`
- Test: `tests/test_ops_waiting.py`, `tests/test_cli_controls.py`
- Docs: `docs/modules/ops/README.md`, `docs/modules/cli/README.md`

**Interfaces:**
- Produces:
  - `WAIT_TYPES = ("ticket.needs_approval", "ticket.stalled", "ticket.failed", "ticket.awaiting_merge", "ticket.merged")` plus `ticket.moved` whose `to` starts with `done/`.
  - `check_workers(paths: StorePaths, *, fix: bool = True) -> list[str]`: tickets whose worker died (record whose pid is gone by `lifecycle.pid_alive` or whose heartbeat is older than `lifecycle.DEAD_AFTER_S`, or an `in_process` ticket at a step status with no record). With `fix`: `fail_ticket(..., "worker died")`, `drop_worker`.
  - `ping(paths: StorePaths, project: str | None) -> None`: `ConductorPing` for the nearest ancestor process named `claude`, `codex` or `agy` (walk parents with `ps -o ppid=,comm= -p <pid>`, at most 20 levels), else the parent; `agent` is `$HARNESS_AGENT`, else the detected name, else `unknown`.
  - `WaitEvent(id, project, status, loop, loop_max, detail)`; `WaitResult(events: list[WaitEvent], idle: bool, timed_out: bool)`.
  - `wait(project: str | None, *, timeout: float, poll_s: float = 1.0) -> WaitResult`: scope `project or "all"`; `check_workers` and `ping` first. No cursor yet → save `journal.end` as the cursor first, then report the open gates of the scope's tickets (`workspace.GATES`); a non-empty list returns at once (saving the cursor before the scan means a gate reached meanwhile is reported, at worst twice, never missed). Then loop: `journal.read_after` → keep `WAIT_TYPES` events of the scope (each event's `status`, `loop`, `loop_max`, `reason`), save the cursor; events → return; no ticket in scope running (an `in_process` sub-status outside `GATES` and `paused`) → `idle`; past the deadline → `timed_out`; else sleep `poll_s` and `check_workers`.
- CLI: `wait [--project P] [--timeout 540]` → `<id> <status> loop n/max: <detail>` per event (capped), `idle`, or exit 3 with `wait timed out after <timeout> s` on stderr. `next` runs `check_workers` and `ping`; `doctor` reports `f"worker of {id} died; run: harness doctor --fix"` and with `--fix` marks it (`fixed=True`).

- [ ] **Step 1: Write the failing tests** in `tests/test_ops_waiting.py`

```python
def test_a_dead_worker_fails_its_ticket(engine: Engine, journal_events: Events) -> None:
    runtime.save_worker(
        engine.paths, WorkerRecord(id="7b55e0c1", project=engine.slug, pid=2**22 + 7)
    )
    assert waiting.check_workers(engine.paths) == ["7b55e0c1"]
    doc = engine.ticket()
    assert doc.meta.status == "in_process/failed" and doc.meta.step == "plan"
    event = journal_events()[-1]
    assert (event["type"], event["reason"]) == ("ticket.failed", "worker died")
    assert runtime.load_worker(engine.paths, "7b55e0c1") is None


def test_a_stale_heartbeat_counts_as_dead(engine: Engine) -> None:
    old = utc_now() - timedelta(seconds=lifecycle.DEAD_AFTER_S + 5)
    runtime.save_worker(
        engine.paths,
        WorkerRecord(id="7b55e0c1", project=engine.slug, pid=os.getpid(), heartbeat=old),
    )
    assert waiting.check_workers(engine.paths, fix=False) == ["7b55e0c1"]
    assert engine.ticket().meta.status == "in_process/under_planning"


def test_wait_reports_open_gates_first_then_new_events_once(engine: Engine) -> None:
    doc = engine.ticket()
    doc.meta.status = "in_process/needs_approval"
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    first = waiting.wait(None, timeout=1)
    assert [(e.id, e.status) for e in first.events] == [("7b55e0c1", "in_process/needs_approval")]
    assert waiting.wait(None, timeout=1).idle  # nothing running, nothing new
    steps.fail_ticket(engine.paths, engine.slug, "7b55e0c1", "boom")  # a gate already: no change
    doc = engine.ticket()
    doc.meta.status = "in_process/under_implementation"
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    steps.fail_ticket(engine.paths, engine.slug, "7b55e0c1", "boom")
    second = waiting.wait(None, timeout=1)
    assert [(e.status, e.detail) for e in second.events] == [("in_process/failed", "boom")]


def test_wait_times_out_while_work_runs(engine: Engine) -> None:
    runtime.save_ticket_state(engine.paths, "7b55e0c1", TicketState())
    runtime.save_worker(
        engine.paths, WorkerRecord(id="7b55e0c1", project=engine.slug, pid=os.getpid())
    )
    waiting.wait(None, timeout=0.1)  # sets the cursor
    result = waiting.wait(None, timeout=0.3, poll_s=0.1)
    assert result.timed_out and not result.events


def test_ping_records_the_conductor(
    store_paths: StorePaths, registered_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HARNESS_AGENT", "codex")
    waiting.ping(store_paths, "payments-api")
    [ping] = [json.loads(p.read_text()) for p in store_paths.conductors.glob("[0-9]*.json")]
    assert (ping["agent"], ping["project"]) == ("codex", "payments-api")
```

In `tests/test_cli_controls.py`: `wait` on an empty store prints `idle` and exits 0; `doctor` with a dead worker record prints `payments-api: worker of 7b55e0c1 died; run: harness doctor --fix` and exits 1.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_ops_waiting.py tests/test_cli_controls.py`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement** `ops/waiting.py`, the `next` and `doctor` hooks and the CLI command. `fail_ticket` journals `status_event`, so every gate event carries `status`, `loop`, `loop_max` and `reason`; check that `run_job`'s halts, `merge_ticket` and `stop_ticket` do too.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_ops_waiting.py tests/test_cli_controls.py tests/test_cli_queue.py tests/test_cli_projects.py && make lint type`
Expected: PASS.

- [ ] **Step 5: Document and commit**

```bash
git add src/super_harness/ tests/ docs/modules/
git commit -m "feat(ops): wait for gates, find dead workers, record conductor pings"
```

---

### Task 11: ticket changes and ticket attach

**Files:**
- Create: `src/super_harness/ops/changes.py`
- Modify: `src/super_harness/gitops.py` (`branch_exists`, `show`), `src/super_harness/cli.py`
- Test: `tests/test_ops_changes.py`
- Docs: `docs/modules/ops/README.md`, `docs/modules/gitops/README.md`, `docs/modules/cli/README.md`

**Interfaces:**
- Produces:
  - `gitops.branch_exists(repo: Path, branch: str) -> bool`; `gitops.show(repo: Path, sha: str) -> str` (`git show --format=%H%n%s <sha>`).
  - `Change(path, added: int | None, removed: int | None, loop: str, step: str, model: str, commit: str)`; `Changes(id, project, ref, changes: list[Change], diff: str)`; `ticket_changes(ticket_id, *, diff: bool, project) -> Changes`: `ref` is the ticket branch when it exists, else the base branch; each commit of `gitops.ticket_commits(repo, uuid, ref)` gives one `Change` per file, from trailers `Harness-Loop`, `Harness-Step`, `Harness-Model`; `diff=True` joins `gitops.show` of each commit. No commits → `UserError(f"{id} has no commits yet")`.
  - `Attach(id, project, role, command: str)`; `attach_command(ticket_id, *, role: str | None, project) -> Attach`: `role` defaults to the role of `ticket.step` when it has a session, else the last session written; `command = f"cd {shlex.quote(str(worktree or repo))} && {shlex.join(adapter.attach_command(session.id))}"`. No session → `UserError(f"{id} has no {role} session")` (or `has no sessions`).
- CLI: `ticket changes ID [--diff]` → `<path> +a -r  loop n <step> <provider>/<model>` per file and commit (binary files show `+- --`), then the diff with `--diff`; `ticket attach ID [--role R]` → the command.

- [ ] **Step 1: Write the failing tests** in `tests/test_ops_changes.py`

```python
def test_changes_list_files_with_their_loop_and_model(engine: Engine) -> None:
    (engine.worktree / "retry.py").write_text("a = 1\nb = 2\n")
    trailers = {
        "Harness-Ticket": str(engine.ticket().meta.uuid),
        "Harness-Step": "implement",
        "Harness-Loop": "1",
        "Harness-Agent": "implementer",
        "Harness-Model": "codex/default",
    }
    sha = gitops.commit_all(engine.worktree, "hrn(7b55e0c1): loop 1 implement: retry", trailers)
    found = changes.ticket_changes("7b55e0c1", diff=True, project=None)
    assert found.ref == "hrn/7b55e0c1"
    assert found.changes == [Change("retry.py", 2, 0, "1", "implement", "codex/default", sha)]
    assert "+b = 2" in found.diff


def test_attach_prints_the_resume_command(engine: Engine) -> None:
    doc = engine.ticket()
    doc.meta.sessions["planner"] = SessionRef(provider="claude", model="opus", id="s-1")
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    found = changes.attach_command("7b55e0c1", role=None, project=None)
    assert found.command == f"cd {shlex.quote(str(engine.worktree))} && claude --resume s-1"
    with pytest.raises(UserError, match="7b55e0c1 has no implementer session"):
        changes.attach_command("7b55e0c1", role="implementer", project=None)
```

Add CLI tests to `tests/test_cli_controls.py`: `ticket changes 7b55e0c1` prints `retry.py +2 -0  loop 1 implement codex/default`; `ticket attach 7b55e0c1` prints the command.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_ops_changes.py`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement** the gitops helpers, `ops/changes.py` and the two CLI commands.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_ops_changes.py tests/test_cli_controls.py && make lint type`
Expected: PASS.

- [ ] **Step 5: Document and commit**

```bash
git add src/super_harness/ tests/ docs/modules/
git commit -m "feat(ops): ticket changes and ticket attach"
```

---

### Task 12: Integration lifecycle and status

**Files:**
- Create: `tests/test_lifecycle.py`
- Modify: `docs/architecture.md` (worker and ops rows; SP3 row "M1–M3 built; M4 plan review, compaction, live next"), `AGENTS.md` (status line), `docs/superpowers/specs/2026-10-22-sp3-engine-design.md` (tick the §12 boxes M3 meets)

- [ ] **Step 1: Write the lifecycle test** (SP3 spec §11): a registered repo, a ticket added through `harness ticket add` on an approved quick plan (or saved directly as in `engine`, `in_queue/ready`, workflow `simple`), the fakes queued for plan → implement → review fails → implement → review passes, then through the CLI: `run` (real detached worker) → `wait --timeout 60` reports `awaiting_merge` → `merge` → `done/merged`. Assert: every claude and codex call ran in the worktree; the second review resumed the first review's session; `git log --grep "Harness-Ticket: <uuid>"` on `main` finds two `implement` commits; `step.end` events carry `provider`, `model`, `session`, `tokens`, `duration_s` and `verdict`; no worker record is left.

```python
def test_a_ticket_goes_from_ready_to_merged(
    lifecycle_repo: Engine, fake_clis: FakeClis, run_git: Callable[..., str], journal_events: Events
) -> None:
    queue_happy_path(fake_clis)  # the five replies of Task 5's full workflow test
    assert runner.invoke(app, ["run", "7b55e0c1"]).stdout == "started 7b55e0c1 plan→claude\n"
    waited = runner.invoke(app, ["wait", "--timeout", "60"])
    assert waited.exit_code == 0 and waited.stdout.startswith(
        "7b55e0c1 in_process/awaiting_merge loop 2/3"
    )
    assert (
        runner.invoke(app, ["merge", "7b55e0c1"]).stdout == "merged 7b55e0c1: 2 commits into main\n"
    )
    uuid = lifecycle_repo.ticket().meta.uuid
    grep = run_git(
        lifecycle_repo.repo, "log", "--format=%s", f"--grep=Harness-Ticket: {uuid}", "main"
    )
    assert len(grep.splitlines()) == 2
    ends = [e for e in journal_events() if e["type"] == "step.end"]
    assert len(ends) == 5 and all(
        {"provider", "model", "session", "tokens", "duration_s", "verdict"} <= e.keys()
        for e in ends
    )
    assert runtime.load_workers(lifecycle_repo.paths) == []
```

`lifecycle_repo` is `engine` with the ticket at `in_queue/ready`, no step and no worktree (a fixture in this file).

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_lifecycle.py`
Expected: PASS (fix the units, not the test, when it fails).

- [ ] **Step 3: Update the status docs and run everything**

Run: `make check`
Expected: PASS.

- [ ] **Step 4: Review every M3 change against the spec**

Walk SP3 spec §2 (decisions 1, 2, 5, 7–13, 17, 18, 20–27), §4, §5, §8.2, §9, §10 (every command row M3 owns) and §12, and system spec §5, §6 and §7.1, against `git diff <M2 head>...HEAD`. Confirm every row has a test, the five Review Focus inputs are tested, and `worker` imports only `ops` and `model`. Fix gaps in place, each with a test.

- [ ] **Step 5: Commit**

```bash
git add tests/test_lifecycle.py docs/ AGENTS.md
git commit -m "test: full ticket lifecycle with detached workers; SP3 M3 built"
```
