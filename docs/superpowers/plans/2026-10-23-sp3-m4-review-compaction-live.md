# SP3 M4: Plan Review, Compaction and Live Smoke Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `harness plan review` (reviewer rounds on another provider, resumed per plan), `harness memory compact` (and background compaction from `memory add`), the DECISIONS archive, and live smoke tests that run real CLIs, closing SP3.

**Architecture:** Two new job kinds join the ticket job: `python -m super_harness.worker plan-review <id>` and `... compact`. `ops.jobs` starts them, tracks their worker records and waits for their terminal journal event (`plan.reviewed` / `memory.compacted`, or `worker.exited` on failure). `ops.calls` holds the retry rules (timeout once, schema repair once) that ticket steps, reviews and compaction share. `ops.reviews` and `ops.compaction` are the use cases; `memory` owns the MEMORY.md and DECISIONS.md writes (compaction checks, archive).

**Tech Stack:** Python 3.12, pydantic 2, Typer, subprocess, filelock, pytest, import-linter, uv.

**Spec:** `docs/superpowers/specs/2026-10-22-sp3-engine-design.md` (§1 M4, decisions 14–15, §10 `plan review` and `memory compact`, §11 live smoke, §12), with system spec `2026-10-22-super-harness-design.md` §4.4, §4.5, §5, §6, §6.1.

## Global Constraints

- The spec is the contract; Task 1 records the decisions this plan takes where the spec is silent.
- A change to `src/super_harness/<module>` updates `docs/modules/<module>/README.md` in the same commit (`make docs`, pre-commit hook).
- Import layers stay `cli | worker > ops > memory > journal | settings > store > model`; `worker` reaches the store only through `ops`.
- Only `harness` writes store files. Plan writes happen under `runtime/locks/<slug>.lock`, MEMORY.md and DECISIONS.md writes under `memory.lock`; compaction starts under `compact.lock`.
- `ops` functions return dataclasses; the CLI formats them. Status and action commands print at most 5 lines (`_capped`); `--json` prints everything.
- Exit codes: 0 ok · 1 error · 3 wait timeout (`WaitTimeout`, new) · 4 setup needed · 5 user decision.
- No test outside `tests/live/` runs a real provider; live tests are opt-in (`-m live`) and excluded from `make check`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. The user saves, approves or rejects a plan while its review runs: the round's result is dropped and the waiting `plan review` reports it instead of hanging (Task 4).
2. `plan review` times out (exit 3) and is called again: it waits for the same job; it never starts a second reviewer (Task 5).
3. `memory add` runs while compaction is in flight: the new line survives the compacted file (Task 6).
4. A compaction result that drops a `(pin)` line or a `##` heading, or is not under the cap, leaves MEMORY.md untouched (Task 6).
5. A plan-review or compaction worker killed mid-call: its record is dropped, its slot freed, and the next `plan review` restarts the round (Tasks 3, 5).

---

### Task 1: Record the M4 decisions in the specs

**Files:**
- Modify: `docs/superpowers/specs/2026-10-22-sp3-engine-design.md` (§2: decisions 28–35; §4: `tickets/<id>.json` also serves plan ids and the compaction job)
- Modify: `docs/superpowers/specs/2026-10-22-super-harness-design.md` (§6.1: add `memory.compacted`)

- [ ] **Step 1: Append to SP3 §2**

```markdown
28. **Plan review job.** `harness plan review` refreshes `review.max` from `plan.review_max`, picks the reviewer (decision 14), records it as `review.reviewer`, sets the plan `in_review`, starts `python -m super_harness.worker plan-review <id>` and waits for that round's `plan.reviewed` event (or the job's `worker.exited`) up to `--timeout`. A timed-out review keeps running; `plan review` again waits for it; a round that already has a verdict is reprinted, never rerun. A round counts only once it has a verdict. A fail at round `review.max`, or a call after it, exits 5: the user approves (overriding) or rejects. `plan save` sets the plan back to `draft` and keeps the round count. `plan.review_max: 0` makes `plan review` an error.
29. **Plan review rounds** run read-only in the project's main working tree. A new session gets the role skill, the plan's sections (all but the Review log) and the newest 40 project and global DECISIONS.md entries; a resumed round gets the plan again plus its Review log. Findings append to the Review log as `- round <r> · <severity> · <file>:<line> · <issue> · <fix>`, a pass as `- round <r> · pass · <summary>`. Rounds take a slot like steps; a timeout and a schema error each retry once; any other error, or a plan changed during the round, ends the job without a round (`worker.exited`, `ok: false`). With `different-provider` and no other usable provider, the review runs on the conductor's provider and `plan review` warns.
30. **Plan approval** is refused (exit 5) while the latest round failed and rounds are left, unless `--skip-review`.
31. **Compaction job.** `python -m super_harness.worker compact` (one at a time; worker id `compact`) runs `memory.compactor` read-only in `memory/`, a new session each time, asking for at most ¾ of `memory.compact_at_lines` lines and keeping the title, intro, every `##` heading and every `(pin)` line verbatim. Lines added while it ran are merged back into their sections; the result is accepted only with fewer lines than `memory.compact_at_lines`, every heading and every pinned line. Accepted: MEMORY.md is replaced and committed. Either way `memory.compacted` is journaled with `before`, `after`, `accepted` and `reason`. `memory compact` exits 1 on a rejection. `memory add` starts the job when MEMORY.md passes the cap, unless it runs already.
32. **DECISIONS archive.** When `memory add --decision` takes DECISIONS.md past 300 lines, its oldest entries move, oldest first, to `memory/archive/DECISIONS.md` until it has 300 lines again; the `memory.write` event counts them (`archived`).
33. **Job workers.** Plan-review and compaction workers write `workers/<id>.json` with their `job`, heartbeat like ticket workers, and journal `worker.exited` (`job`, `ok: false`, `reason`) when they fail. The dead-worker check drops a dead job's record, frees its slot and journals `worker.exited` "worker died". `wait` reports `plan.reviewed` events, a reviewed plan awaiting approval counts as an open gate, and a running plan review counts as running work.
34. **Resuming a stalled ticket** clears its stall streaks and its failing `review_plan` rounds.
35. **Live smoke** runs with `uv run pytest -m live` (or `make live`), never in `make check`. For each provider installed and signed in: one ticket through plan → implement → review_code → merge, one plan-review round and one compaction, on claude `haiku`, agy `gemini-3.8-flash-low` or codex's default (`HARNESS_LIVE_<PROVIDER>_MODEL` overrides).
```

- [ ] **Step 2: Edit SP3 §4** — the `tickets/<id>.json` line gains `; for plan ids and the compaction job: call count and reviewer totals`.

- [ ] **Step 3: Edit system spec §6.1** — add `memory.compacted` after `memory.write` in the type list.

- [ ] **Step 4: Check and commit**

Run: `make docs` — Expected: no output.

```bash
git add docs/superpowers/specs docs/superpowers/plans/2026-10-23-sp3-m4-review-compaction-live.md
git commit -m "docs: SP3 M4 plan and decisions for plan review, compaction and live smoke"
```

---

### Task 2: Shared call retries and the wait-timeout error

**Files:**
- Create: `src/super_harness/ops/calls.py`
- Modify: `src/super_harness/ops/steps.py` (use `calls`), `src/super_harness/model/errors.py`, `src/super_harness/model/__init__.py`
- Test: `tests/test_ops_calls.py`
- Docs: `docs/modules/ops/README.md`, `docs/modules/model/README.md`

**Interfaces:**
- Produces:
  - `model.WaitTimeout(HarnessError)`, `exit_code = 3`.
  - `calls.plus(a: Usage, b: Usage) -> Usage` (was `steps._plus`).
  - `calls.again(request: StepRequest, result: StepResult | None, log: Path) -> StepRequest` (was `steps._again`, log passed in).
  - `calls.repair(request: StepRequest, result: StepResult, problem: str, log: Path) -> StepRequest` (was `steps._repair`; without a session it is `again`).
  - `calls.failure(provider: str, request: StepRequest, result: StepResult) -> str` (was `steps._failure`; `BINARIES` moves too).
  - `@dataclass calls.Called(request: StepRequest, result: StepResult, usage: Usage)`.
  - `calls.call(paths: StorePaths, provider: str, request: StepRequest, next_log: Callable[[], Path]) -> Called`: a `timeout` retries once (`again`), a `schema` error gets one repair turn (`repair`); any other result returns at once; `usage` sums every attempt.

- [ ] **Step 1: Write the failing tests** in `tests/test_ops_calls.py`, with a `Scripted` provider (monkeypatched over `adapters.get`) that returns queued `StepResult`s and records each request:
  - `test_a_timeout_retries_once_on_a_fresh_log`: `[timeout, ok]` → 2 requests, different `log`, `called.result.ok`, usage summed.
  - `test_a_second_timeout_is_returned`: `[timeout, timeout]` → 2 requests, `called.result.error == "timeout"`.
  - `test_a_schema_error_gets_one_repair_turn_on_the_session`: `[schema(session_id="s1"), ok]` → second request `resume is True`, `session_id == "s1"`, `skill is None`, prompt starts with `"Your last reply failed"`.
  - `test_other_errors_return_at_once`: `[auth]` → 1 request.

- [ ] **Step 2: Run** `uv run pytest tests/test_ops_calls.py` — Expected: FAIL (`No module named 'super_harness.ops.calls'`).

- [ ] **Step 3: Implement `calls`, move the helpers out of `steps`** (steps keeps its own `_call` loop for rate limits and fallbacks, calling `calls.again/repair/plus/failure`), add `WaitTimeout`.

- [ ] **Step 4: Run** `uv run pytest tests/test_ops_calls.py tests/test_ops_steps.py` — Expected: PASS.

- [ ] **Step 5: Commit** `refactor(ops): share call retries; add WaitTimeout`.

---

### Task 3: Job workers: start, track, wait, and clean up after dead ones

**Files:**
- Create: `src/super_harness/ops/jobs.py`
- Modify: `src/super_harness/model/runtime.py` (`WorkerRecord.job`), `src/super_harness/ops/controls.py` (`spawn_worker` uses `jobs.spawn`), `src/super_harness/ops/waiting.py` (`dead_workers` returns records; `check_workers` dispatches by job), `src/super_harness/ops/projects.py` (doctor wording), `src/super_harness/worker/__main__.py` (`jobs.heartbeat` / `jobs.forget`), `src/super_harness/ops/steps.py` (drop `heartbeat`, `forget_worker`)
- Test: `tests/test_ops_jobs.py`, `tests/test_ops_waiting.py`
- Docs: ops, model, worker READMEs

**Interfaces:**
- Produces:
  - `WorkerRecord.job: Literal["ticket", "plan-review", "compact"] = "ticket"`.
  - `jobs.COMPACT = "compact"` (the compaction worker's id).
  - `jobs.spawn(paths: StorePaths, args: Sequence[str], log_name: str) -> int`: `python -m super_harness.worker *args`, new session, output to `runtime/logs/<log_name>.log`.
  - `jobs.start(paths, job: str, job_id: str, project: str, args: Sequence[str]) -> int`: spawn, then save the worker record.
  - `jobs.alive(paths, job_id: str) -> WorkerRecord | None`: the record when its pid lives and its heartbeat is fresh.
  - `jobs.heartbeat(job_id: str) -> None`, `jobs.forget(job_id: str) -> None` (own pid only; moved from `steps`).
  - `jobs.exited(job: str, job_id: str, project: str | None, reason: str) -> Event`: `worker.exited` with `job`, `ok: False`, `reason`, and `plan` set for plan reviews.
  - `jobs.await_event(paths, cursor: JournalCursor, match: Callable[[Event], bool], job_id: str, *, timeout: float, poll_s: float = 0.5) -> Event | None`: the first matching event after `cursor`; when the worker is gone, one last read, then a synthetic `worker.exited` "worker died; log: runtime/logs/<id>.log"; `None` at the timeout.
  - `jobs.take_slot(paths, entry: SlotEntry) -> None`: acquire, polling every `SLOT_POLL_S` and heartbeating `entry.ticket`.
  - `jobs.died(paths, record: WorkerRecord) -> None`: free the job's slot and journal `worker.exited` "worker died".
  - `waiting.dead_workers(paths) -> list[WorkerRecord]`.

- [ ] **Step 1: Write the failing tests**
  - `test_spawn_starts_a_detached_worker_that_logs` (`jobs.spawn(paths, ["--help"], "probe")`, wait for exit, log contains `usage:`).
  - `test_alive_needs_a_live_pid_and_a_fresh_heartbeat` (own pid → record; pid `2**22 + 7` → None; heartbeat 3 minutes old → None).
  - `test_await_event_returns_the_first_match_after_the_cursor` (an event before the cursor is ignored).
  - `test_await_event_reports_a_dead_worker` (no record → `worker.exited` with `"worker died"`) and `test_await_event_times_out` (live record, nothing journaled, `timeout=0.2` → None).
  - In `tests/test_ops_waiting.py`: `test_dead_job_workers_are_dropped_and_free_their_slot` (a `plan-review` record with a dead pid and a held slot → `check_workers` returns its id, record and slot gone, `worker.exited` journaled; no ticket touched).

- [ ] **Step 2: Run** them — Expected: FAIL (no `ops.jobs`).

- [ ] **Step 3: Implement**; `worker` uses `jobs.heartbeat`/`jobs.forget`; doctor says `worker of <id> died; marked failed` for tickets and `...; dropped` for jobs.

- [ ] **Step 4: Run** `uv run pytest tests/test_ops_jobs.py tests/test_ops_waiting.py tests/test_worker.py tests/test_ops_projects.py` — Expected: PASS.

- [ ] **Step 5: Commit** `feat(ops): job workers for plan reviews and compaction`.

---

### Task 4: The plan-review job

**Files:**
- Create: `src/super_harness/ops/reviews.py`
- Modify: `src/super_harness/ops/prompts.py`, `src/super_harness/ops/agents.py` (`problem` public), `src/super_harness/worker/__main__.py` (`plan-review <id> [--project]`)
- Test: `tests/test_ops_reviews.py`, `tests/test_worker.py`
- Docs: ops, worker READMEs

**Interfaces:**
- Consumes: `calls.call`, `calls.failure`, `jobs.take_slot`, `jobs.exited`, `agents.pick`, `agents.detector`.
- Produces:
  - `prompts.PLAN_REVIEW` (one-line instruction), `prompts.plan_review_prompt(plan: Plan, sections: Mapping[str, str], decisions: str, *, round: int, resumed: bool) -> str`, `prompts.review_log_lines(round: int, output: ReviewOutput) -> list[str]`.
  - `agents.problem(provider: str, status: Callable[[str], ProviderStatus]) -> str | None`.
  - `reviews.ROLE = "plan-reviewer"`, `reviews.PROVIDERS = ("claude", "codex", "antigravity")`, `reviews.DECISION_LINES = 40`.
  - `reviews.conductor_provider(by: str) -> str | None`: `claude|codex` as is, `agy|antigravity` → `antigravity`; otherwise `claude` when `CLAUDECODE=1`; else None.
  - `reviews.choose_reviewer(resolved: Settings, conductor: str | None, detect: Callable[[str], ProviderStatus]) -> tuple[agents.Pick, str]`: the pick and a warning (decisions 14, 29); `UserError` when the role is off; `NeedsSetup` when nothing is usable.
  - `reviews.run_review(plan_id: str, *, project: str | None) -> str` (worker body; journals exactly one of `plan.reviewed` or `worker.exited`), `reviews.fail_review(plan_id: str, *, project: str | None, reason: str) -> None`.
  - `plan.reviewed` event: `project, plan, round, max, verdict, summary` (first line), `findings` (count), `fingerprints, reviewer` (`provider/model`), `session, tokens {in,out,cache_read,cache_write}, duration_s`.

- [ ] **Step 1: Write the failing tests** (fixture: a direct plan saved with Goal, Scope, Design and Acceptance, set `in_review` with `review.reviewer`, as Task 5's start leaves it):
  - `test_conductor_provider_reads_by_then_claudecode`.
  - `test_choose_reviewer_avoids_the_conductors_provider` (plan-reviewer `{cli: claude, fallback: [antigravity/gemini-3.8-flash-low]}`: conductor claude → antigravity/gemini-3.8-flash-low; codex → claude; None → claude).
  - `test_choose_reviewer_takes_another_signed_in_provider` (no fallback, conductor claude, codex signed out → antigravity, model None).
  - `test_choose_reviewer_warns_when_only_the_conductors_provider_is_usable` (codex hidden, agy signed out → claude, warning contains `"no other provider"`).
  - `test_a_named_reviewer_is_used_directly` (`plan.reviewer: antigravity/gemini-3.8-flash-low`).
  - `test_a_review_round_records_verdict_session_and_review_log` (fake claude fail with one finding): round 1, verdict fail, `review.session.id` from the reply, Review log `- round 1 · medium · …`, `plan.reviewed` with `round: 1, max: 2, findings: 1`, slot released, the call ran in the repo with `--permission-mode dontAsk`, the prompt holds `## Prompt` and the Goal.
  - `test_the_next_round_resumes_the_reviewer_session` (after round 1, the plan back `in_review` without a verdict) → `--resume <id>`, prompt starts `Round 2 of 2`.
  - `test_a_failed_call_ends_the_job_without_a_round` (claude `api_error_status` 401) → round 0, verdict None, `worker.exited` with `ok: false` and `"sign in to claude"`.
  - `test_a_plan_saved_during_the_round_keeps_the_users_version` (`calls.call` wrapped to run `plans.save_plan` first) → status draft, round 0, `worker.exited` reason mentions `changed`.
  - In `tests/test_worker.py`: `test_the_worker_runs_a_plan_review` (`python -m super_harness.worker plan-review <id> --project payments-api` exits 0, round 1 written).

- [ ] **Step 2: Run** — Expected: FAIL (no `ops.reviews`).

- [ ] **Step 3: Implement** `run_review`: under the lock read the round and reviewer; detect the provider; take a slot (`ticket=<plan id>`, `step=review_plan`); build the request (cwd: repo; profile read_only; output review; claude new sessions get a uuid; `prior_usage` from `runtime` state of the plan id; logs `<plan id>-<n>.out`); `calls.call`; release the slot; on an error drop a resumed session and exit; under the lock drop a result whose plan changed (status not `in_review`, or round or verdict moved), else write round, verdict, session, Review log, totals and journal `plan.reviewed` with a store commit.

- [ ] **Step 4: Run** `uv run pytest tests/test_ops_reviews.py tests/test_worker.py` — Expected: PASS.

- [ ] **Step 5: Commit** `feat(ops): plan-review job on another provider, resumed per plan`.

---

### Task 5: `harness plan review`, approval rules and `wait`

**Files:**
- Modify: `src/super_harness/ops/reviews.py`, `src/super_harness/ops/plans.py`, `src/super_harness/ops/waiting.py`, `src/super_harness/cli.py`
- Test: `tests/test_ops_reviews.py`, `tests/test_ops_plans.py`, `tests/test_ops_waiting.py`, `tests/test_cli_plans.py`
- Docs: ops, cli READMEs

**Interfaces:**
- Produces:
  - `@dataclass reviews.ReviewRound(id: str, project: str, round: int, max: int, verdict: str, findings: list[str], reviewer: str, warning: str = "")` with property `used_up` (`verdict == "fail" and round >= max`).
  - `reviews.review_plan(plan_id: str, *, project: str | None, by: str, timeout: float, poll_s: float = 0.5) -> ReviewRound` (decision 28): `UserError` (review off, not draft or in_review, nothing to review, job failed), `NeedsUser` (rounds used up), `NeedsSetup`, `WaitTimeout`.
  - `plans.approve_plan`: accepted when `review_max == 0`, quick, `verdict == "pass"` or `round >= review_max`; else `--skip-review`; a failed round with rounds left says `failed review round r of max; save a revision and run: harness plan review <id>, or approve with --skip-review`.
  - `waiting.WaitEvent.kind: str = "ticket"` (`"plan"` for `plan.reviewed`: `status` = verdict, `loop`/`loop_max` = round/max, `detail` = summary); `plan.reviewed` in `WAIT_TYPES`; `_open_gates` adds plans `in_review` with a verdict; `_running` counts live plan-review workers in scope.
  - CLI `harness plan review ID [--timeout 540] [--project P] [--by B] [--json]`: `plan <id> round r: pass|fail, N findings`, a `warning:` line when set, then the findings, capped with `+N more; run: harness plan show <id>`; `used_up` → stderr `review rounds used up (r/max): the user approves the plan as it is or rejects it`, exit 5. `harness wait` prints plan events as `plan <id> round r/max: <verdict>, <summary>`.

- [ ] **Step 1: Write the failing tests**
  - `test_cli_plan_review_runs_a_round_and_prints_findings` (real detached worker, fake claude fail with 2 findings; `--by codex`) → exit 0, first line `plan <id> round 1: fail, 2 findings`, then 2 finding lines.
  - `test_plan_review_reprints_a_finished_round` (second call → same output, no new fake call).
  - `test_a_failing_last_round_exits_5` (`plan.review_max: 1`).
  - `test_used_up_rounds_refuse_another_review` (round 1 of 1 failed, plan saved again → exit 5, no call).
  - `test_a_timed_out_review_keeps_running_and_a_second_call_waits_for_it` (fake `sleep=2`, `--timeout 0.3` → exit 3; again with `--timeout 30` → round 1; one fake call).
  - `test_plan_review_is_off_at_review_max_zero` and `test_a_plan_without_sections_has_nothing_to_review` (exit 1).
  - `test_approve_refuses_a_failed_round_with_rounds_left`, `test_approve_accepts_a_pass_or_used_up_rounds` (in `tests/test_ops_plans.py`).
  - `test_wait_reports_a_finished_plan_review` and `test_a_running_plan_review_is_not_idle` (in `tests/test_ops_waiting.py`).

- [ ] **Step 2: Run** — Expected: FAIL.

- [ ] **Step 3: Implement** `review_plan` per decision 28: take the journal cursor first; under the project lock attach to a live job, or reprint a round with a verdict, or refuse, or choose the reviewer, mark the plan `in_review`, `jobs.start(...)`, journal `worker.started`; then `jobs.await_event` for `plan.reviewed` with this plan and round, or `worker.exited` with `job == "plan-review"` and this plan. Round findings are the Review log lines starting `- round <r> · `, except its pass line.

- [ ] **Step 4: Run** `uv run pytest tests/test_ops_reviews.py tests/test_ops_plans.py tests/test_ops_waiting.py tests/test_cli_plans.py tests/test_cli_controls.py` — Expected: PASS.

- [ ] **Step 5: Commit** `feat: harness plan review, approval after review, plan events in wait`.

---

### Task 6: Memory compaction

**Files:**
- Create: `src/super_harness/ops/compaction.py`
- Modify: `src/super_harness/memory.py`, `src/super_harness/ops/prompts.py`, `src/super_harness/ops/workspace.py` (`remember` starts it), `src/super_harness/worker/__main__.py` (`compact`), `src/super_harness/cli.py` (`memory compact`, `memory add` notice)
- Test: `tests/test_memory.py`, `tests/test_ops_compaction.py`, `tests/test_cli_workspace.py`
- Docs: memory, ops, worker, cli READMEs

**Interfaces:**
- Produces:
  - `memory.AddResult.compacting: bool = False`.
  - `@dataclass memory.Compaction(before: int, after: int, accepted: bool, reason: str = "")`.
  - `memory.compaction_problem(current: list[str], result: list[str], cap: int) -> str | None`: checked in order: empty → `the result is empty`; a dropped pinned line → `the result drops N pinned line(s): <first>`; a dropped heading → `the result drops the heading <h>`; `len(result) >= cap` → `the result has N lines; the cap is C`.
  - `memory.merge_added(snapshot: list[str], current: list[str], result: list[str]) -> list[str]`: entries in `current` but not `snapshot` go into their section in `result` (`_insert`), unless already there.
  - `memory.apply_compaction(paths, snapshot: str, text: str, *, cap: int, detail: Mapping[str, Any]) -> Compaction`: under `memory.lock`; redacted; journals `memory.compacted` (`file, before, after, accepted, reason, by: harness`, plus `detail`); commits when accepted.
  - `prompts.compact_prompt(text: str, *, cap: int) -> str` (decision 31; the file inside a fenced block).
  - `compaction.run_compaction() -> str` (worker body; journals `memory.compacted` or `worker.exited`), `compaction.fail_compaction(reason: str) -> None`, `compaction.start_background(paths) -> bool` (True when the job runs after the call), `compaction.compact_memory(*, timeout: float, poll_s: float = 0.5) -> memory.Compaction` (`NeedsSetup` when the compactor is unusable, `UserError` when the job fails, `WaitTimeout`).
  - CLI `harness memory compact [--timeout 540] [--json]`: `MEMORY.md N → M lines`, or stderr `MEMORY.md kept (N lines): <reason>` and exit 1. `memory add` over the cap prints `MEMORY.md is over its C-line cap; compacting it in the background`.

- [ ] **Step 1: Write the failing tests**
  - `tests/test_memory.py`: `test_compaction_problem_names_each_rejection` (one case each), `test_merge_added_keeps_lines_written_meanwhile`, `test_apply_compaction_replaces_memory_and_journals`, `test_a_rejected_compaction_leaves_memory_alone`.
  - `tests/test_ops_compaction.py`: `test_run_compaction_accepts_a_shorter_file_that_keeps_pins` (fake claude `{text}`; argv has `--model haiku` and the read-only profile; cwd is `memory/`), `test_run_compaction_rejects_a_result_without_pins`, `test_a_failed_compaction_call_journals_worker_exited`.
  - `tests/test_cli_workspace.py`: `test_memory_compact_prints_the_line_counts` (real worker), `test_memory_compact_exits_1_on_a_rejection`, `test_memory_add_over_the_cap_compacts_in_the_background` (`memory.compact_at_lines: 12`; the add prints the notice; the job's `memory.compacted` arrives).

- [ ] **Step 2: Run** — Expected: FAIL.

- [ ] **Step 3: Implement**: compaction runs on the defaults scope's settings; slot `SlotEntry(provider, project="", ticket="compact", step="compact")`; logs `compact-<n>.out`; `start_background` and `compact_memory` check `jobs.alive` and start under `compact.lock`.

- [ ] **Step 4: Run** `uv run pytest tests/test_memory.py tests/test_ops_compaction.py tests/test_cli_workspace.py` — Expected: PASS.

- [ ] **Step 5: Commit** `feat: memory compaction job, harness memory compact`.

---

### Task 7: DECISIONS archive

**Files:** Modify `src/super_harness/memory.py`; Test `tests/test_memory.py`; Docs memory README.

**Interfaces:** `memory.archive_oldest(lines: list[str], cap: int) -> tuple[list[str], list[str]]` (kept, moved: the oldest `- ` entries beyond `cap`); `memory.ARCHIVE_HEADER`.

- [ ] **Step 1: Write the failing test** `test_decisions_past_300_lines_move_their_oldest_to_the_archive`: DECISIONS.md at 300 lines; two more decisions → file stays at 300 lines, `memory/archive/DECISIONS.md` holds the header then the two oldest entries in order, the last `memory.write` has `archived: 1`.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** in the decision branch of `memory.add`, under the same lock.
- [ ] **Step 4: Run** `uv run pytest tests/test_memory.py` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(memory): archive the oldest decisions past 300 lines`.

---

### Task 8: Resuming a stalled ticket clears its plan-review rounds

**Files:** Modify `src/super_harness/ops/controls.py`; Test `tests/test_ops_controls.py`; Docs ops README.

- [ ] **Step 1: Write the failing test** `test_resuming_a_stalled_ticket_clears_its_plan_rounds` (stalled, `plan_rounds: 2`, streaks set → after `run_tickets`, both empty).
- [ ] **Step 2: Run** — Expected: FAIL (`plan_rounds == 2`).
- [ ] **Step 3: Implement** beside the streak reset.
- [ ] **Step 4: Run** `uv run pytest tests/test_ops_controls.py` — Expected: PASS.
- [ ] **Step 5: Commit** `fix(ops): resuming a stalled ticket clears its plan-review rounds`.

---

### Task 9: Live smoke

**Files:**
- Modify: `pyproject.toml` (`markers = ["live: runs real provider CLIs; opt in with -m live"]`, `addopts = "-q -m 'not live'"`), `Makefile` (`live: uv run pytest -m live -v`)
- Create: `tests/live/conftest.py`, `tests/live/test_live_smoke.py`
- Docs: `docs/modules/ops/README.md` only if code changes; spec §8.1 notes for any CLI fact the runs correct.

**Interfaces:**
- `tests/live/conftest.py`: overrides `fake_clis` with a no-op (real `PATH`); fixtures `live_provider` (parametrized over `claude`, `codex`, `antigravity`; skips unless installed and signed in via `adapters.get(p).detect()`), `live_model(provider) -> str | None` (`haiku`, `gemini-3.8-flash-low`, None; env override), `live_repo` (temp `HARNESS_HOME`, temp git identity, a scratch repo with `calc.py`, registered; settings put every agent, the compactor and `plan.reviewer` on the provider's model, `merge.mode: ask`, `step_timeout_min: 10`, `project.test_cmd: python3 -c "import calc; assert calc.add(2, 3) == 5"`).

- [ ] **Step 1: Write the tests**
  - `test_a_ticket_runs_end_to_end`: `plan new --mode quick`, `plan approve`, `ticket add` (one simple ticket: add `add(a, b)` to `calc.py`), `run`, `wait --timeout 1800` until the ticket is `awaiting_merge` (any other gate fails the test with the worker log tail), `merge`; `calc.add(2, 3) == 5` on main; a commit carries `Harness-Ticket: <uuid>`; sessions recorded for planner, implementer and code-reviewer; every `step.end` has tokens.
  - `test_a_plan_review_round`: a direct plan with sections, `plan review --timeout 900 --by user` → exit 0 or 5, first line `plan <id> round 1: `, Review log has round-1 lines, `review.session` set.
  - `test_memory_compaction`: MEMORY.md with 30 lines (duplicates, two pinned), `memory.compact_at_lines: 24` → `memory compact --timeout 900` exit 0, both pins kept, fewer than 24 lines.
- [ ] **Step 2: Check collection** `uv run pytest` — Expected: same count as before plus 0 (live deselected); `uv run pytest -m live --collect-only -q` lists 9 tests.
- [ ] **Step 3: Run live** `uv run pytest -m live -v` — Expected: claude and antigravity pass, codex skipped (not installed). A failure is a real CLI fact: debug it (superpowers:systematic-debugging), fix the adapter with a recorded fixture and a unit test, and correct spec §8.1.
- [ ] **Step 4: Commit** `test: live smoke for every installed provider`.

---

### Task 10: Docs, acceptance and review

**Files:** `docs/architecture.md` (jobs, reviews, compaction, calls), `AGENTS.md` (status: SP3 done), SP3 spec §12 boxes, module READMEs touched above.

- [ ] **Step 1:** Update docs; tick §12; `make check` — Expected: green.
- [ ] **Step 2: Commit** `docs: SP3 complete`.
- [ ] **Step 3:** Whole-branch review of M4 (`git merge-base main HEAD`..HEAD for M4 commits) against the spec; fix Critical and Important findings test-first; ledger minors.
