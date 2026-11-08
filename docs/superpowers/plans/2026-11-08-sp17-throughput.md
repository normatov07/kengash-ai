# SP17 Throughput Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stuck agents get corrected, finished work starts the next, tickets stop waiting for nothing, context is exact and marked for freshness, and every model is editable on the Agents page.

**Architecture:** No new processes. A watchdog inside each CLI call, resume-with-correction in the step loop, a relay at each worker's end, and deterministic context built by kengash at the moment of use.

**Tech Stack:** Python 3.12+, pydantic, filelock, typer, FastAPI, vanilla JS UI.

**Spec:** `docs/superpowers/specs/2026-11-08-sp17-throughput-design.md`

## Global Constraints

- `make check` green; rule 2: each changed `src/kengash_ai/<module>` updates `docs/modules/<module>/README.md`.
- Defaults: `steering {soft_min 20, wrap_min 10, turns 2, poll_max 8, full_runs_max 2}`, `paths {shared [*.g.dart, *.freezed.dart, *.generated.*], max_overlap 2}`, `context.max_kib 64`, `checks.parallel 0`, `plan.max_files 12`, `review.block_on [high, medium]`, `loop_relay true`.
- Role skills stay within 80 lines and 400 words. Prompts stay under `MAX_PROMPT_BYTES` (120 KiB).
- Never overwrite a project's SETTINGS.md. No commits unless the user asks.

## Review Focus

1. Relay after `kengash pause` or a stopped worker: starts nothing in a paused project.
2. A call stopped just as it finished: a valid output wins over `stuck`.
3. File pack given a binary, huge, absent, or `..` path: skipped or named, never read outside the worktree.
4. A split on a later loop, or one that loses an acceptance line: refused, ticket continues whole.
5. `by_importance` naming an unknown provider or shell: refused at settings load.

---

### Task 1: Contracts
**Files:** `model/settings.py`, `model/steps.py`, `model/runtime.py`, `store/defaults/SETTINGS.md`; test `tests/test_sp17_settings.py`
**Produces:** `Settings.steering|paths|context|loop_relay`, `Checks.parallel`, `PlanReview.max_files`, `ReviewPolicy.block_on`, `Agent.by_importance`; `ErrorKind` gains `stuck`; `StepRequest.soft_s|poll_max|full_runs_max`; `Part`, `PlanOutput.parts`; `TicketState.seen: dict[str, str]`; `RelayIntent(scopes)`.
- [x] Failing tests: defaults; `by_importance` rejects unknown importance, unknown provider, shell. Implement. Pass.

### Task 2: Watchdog and honest interrupted calls
**Files:** create `adapters/watchdog.py`; modify `adapters/process.py`, `base.py`, `claude.py`, `antigravity.py`, `codex.py`; test `tests/test_watchdog.py`
**Produces:** `Signal(kind, command)`, `Watchdog.feed(line) -> str`, `run_process(..., observe=)`, `ProcessResult.stopped`, `CliProvider.signal(event) -> Signal | None`, `CliProvider.usage_so_far(stdout) -> Usage`.
- [x] Tests: 8 `manage_task` polls stop; an edit resets; third `flutter test` stops; soft deadline; stopped call keeps session and usage; valid output wins. Implement. Pass.

### Task 3: Steering, timeouts, crashes
**Files:** `ops/steps.py`, `ops/prompts.py`, `adapters/base.py`; test `tests/test_sp17_steering.py`
- [x] Tests: `stuck` resumes with steer prompt, twice, then fallback; timeout resumes with `timeout_prompt`; crash retries once then falls back; `stream idle timeout` is `network`. Implement. Pass.

### Task 4: Relay
**Files:** create `ops/relay.py`; modify `worker/__main__.py`, `ops/loops.py`, `store/runtime.py`, `cli.py`; test `tests/test_relay.py`
**Produces:** `relay.advance(paths) -> list[str]`, `relay.note_claim`, `relay.note_release`.
- [x] Tests: no intent starts nothing; intent starts runnable; paused project starts nothing; `loop_relay: false`; clears when idle; keeps at a gate; never raises. Implement. Pass.

### Task 5: Path claims and check concurrency
**Files:** `scheduler.py`, `ops/queue.py`, `ops/slots.py`, `ops/steps.py`, `ops/controls.py`, `ops/checks.py`, `ops/merging.py`; test `tests/test_sp17_paths.py`
**Produces:** `scheduler.PathPolicy`, `scheduler.clash(a, b, policy)`, `Limits.paths`, `checks.turn(paths, resolved, beat)`.
- [x] Tests: shared exempt; directory clashes; empty is the whole repo; 2 files allowed, 3 not; `max_overlap 0` strict; semaphore limits. Implement. Pass.

### Task 6: Split
**Files:** `ops/tickets.py`, `ops/steps.py`, `model/steps.py`; test `tests/test_sp17_split.py`
**Produces:** `tickets.split(paths, slug, doc, parts, by) -> list[Event]`, `tickets.split_problem(ticket, sections, parts, resolved) -> str`.
- [x] Tests: parts become tickets; `after` maps to deps; dependents wait for every part; lost acceptance refused; loop 2 refused. Implement. Pass.

### Task 7: Verified context
**Files:** create `ops/context.py`; modify `ops/prompts.py`, `ops/steps.py`, `memory.py`, `gitops.py`; test `tests/test_context.py`
**Produces:** `context.file_pack(worktree, files, *, shared, budget) -> str`, `gitops.changed_between(cwd, old, new)`, `memory.digest(paths, project, root=None)`, `prompts.DELEGATION`.
- [x] Tests: exact contents with blob; binary and huge skipped and named; `..` refused; absent listed; budget honoured; changed-since on resume; stale tag; no age tagging. Implement. Pass.

### Task 8: Review precision
**Files:** `ops/prompts.py`, `ops/steps.py`; test `tests/test_sp17_review.py`
**Produces:** `prompts.checked_findings(findings, worktree, *, step_is_plan_review) -> list[Finding]`.
- [x] Tests: only low findings pass; absent file demoted; line past end demoted; plan review untouched. Implement. Pass.

### Task 9: Models
**Files:** `ops/agents.py`, `ops/queue.py`, `ops/controls.py`, `ops/steps.py`, `ops/views.py`, `ops/agent_config.py`, `adapters/*`, `model/steps.py` or wherever `ProviderStatus` lives, `cli.py`, `ui/app.py`, `ui/static/views/agents.js`; tests `tests/test_sp17_models.py`, UI
**Produces:** `agents.pick(..., importance=None)`, `ProviderStatus.live_models`, `AgentPatch.by_importance`, `kengash agent edit --model-for`.
- [x] Tests: importance CLI first, then `cli`, then fallback; model missing from live list skipped; aliases not skipped; CLI flag; API patch. Implement. Add the UI rows. Pass.

### Task 10: Skills and docs
**Files:** `roles/{implement,plan,review-code,review-plan}/SKILL.md`, `docs/modules/*`, `docs/architecture.md`, `AGENTS.md`, `CHANGELOG.md`
- [x] Update, within caps. `make check` green. Critical review of the whole branch against the spec.
