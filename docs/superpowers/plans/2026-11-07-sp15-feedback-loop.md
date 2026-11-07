# SP15 Feedback Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A failing check reaches the implementer inside the same step and loop as the command, exit code and the lines that say what broke; every prompt names the checks; a sent-back agent knows why; a `BLOCKED:` handoff stops the ticket for the user.

**Architecture:** A pure `adapters/digest.py` turns check output into a headline and an excerpt; the shell adapter returns it on `StepResult.check_output`. `ops/steps.py` runs the checks after an editing step's call (helpers in a new `ops/checks.py`), resumes the session with a fix prompt, records `checks.end`, and reuses a passing result in `run_tests`. `workflow` gains the `blocked` approval; `ops/prompts.py` gains the Checks block, sent-back line and fix prompt.

**Tech Stack:** Python 3.12+, pydantic, Typer, pytest with the fake CLIs in `tests/fakes`, uv.

**Spec:** `docs/superpowers/specs/2026-11-07-sp15-feedback-loop-design.md` (read it; this plan argues from it).

## Global Constraints

- Hard rule 2: every commit that changes `src/kengash_ai/<module>` also changes `docs/modules/<module>/README.md` (`make docs` and the pre-commit hook enforce it). Modules here: `adapters`, `model`, `store`, `workflow`, `ops`, `cli`, `roles`, `ui`.
- Import layers (`make lint`): `adapters` and `workflow` import only `model`.
- Runs on Python 3.12, 3.13 and 3.14 (CI matrix); no 3.13+ only syntax.
- `checks.turns`: default 2, `ge=0`, `le=5`; 0 turns the in-step checks off.
- Digest bounds: 2 lines before and 8 after each marker; the last 2 non-empty lines always kept; at most 60 lines and 4,000 characters; each line at most 300; headline marker text at most 160; with no marker, the last 30 lines; overflow ends with `… <n> more lines; full output: <log>`.
- `## Check output` holds at most 62 lines: headline, fence, 60 digest lines.
- Exact copy (tests pin it):
  - Checks block: ``kengash runs these in the worktree after editing steps; each must exit 0:`` then ``- tests: `<cmd>` `` and ``- lint: `<cmd>` ``.
  - Sent back: `<step> sent this back: <summary>. Fix every Finding below, then run the failing check.` (a check step) or `… Fix every Finding below.` (other steps); user: `The user answered: <note>.`
  - Fix prompt head: ``kengash ran the checks after your reply (fix turn <t> of <n>): <headline>``; tail: `Fix the cause, then rerun that command if your tools allow. Reply again with JSON that matches the schema.`
  - Finding fix: `fix the cause in Check output, then run <command>`.
  - Reuse summary: `<summary> (in <step>, same commit)`.
  - Blocked reason: `blocked: <text>`; default note: `the user resolved what you were blocked on`; refusal: `--note answers a blocked ticket`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Instruction-file caps: docs under `docs/` ≤ 150 lines (specs and plans exempt); role skills within `skill.max_lines: 80`, `skill.max_words: 400`.

## Review Focus

1. A check that prints hundreds of thousands of lines: the digest stays capped and takes well under a second (Task 1 test).
2. A fix-turn reply that is invalid JSON or empty: the step keeps its last valid reply and goes on; the ticket does not fail (Task 6 test).
3. A check that hangs: the in-step checks end at the step timeout with no fix turn; `run_tests` judges (Task 6 test).
4. A reviewer summary with newlines or a secret in it: the sent-back line is one line, redacted, at most 300 characters (Task 5 test).
5. The user parks or moves the ticket during in-step checks: no further fix turn runs and the user's status stands (Task 6 test).

---

### Task 1: Failure digest

**Files:**
- Create: `src/kengash_ai/adapters/digest.py`
- Create: `tests/test_adapters_digest.py`
- Create: `tests/fakes/fixtures/checks/flutter_test_assertion.txt`, `flutter_test_compile.txt`, `flutter_analyze.txt`, `pytest_failure.txt`
- Modify: `docs/modules/adapters/README.md`

**Interfaces:**
- Produces: `Digest(headline: str, text: str, file: str = "", line: int = 0)` (frozen dataclass); `excerpt(output: str, *, command: str, exit_code: int, cwd: Path, log: Path) -> Digest`; `section(digest: Digest) -> str`.

- [ ] **Step 1: Make the fixtures.** Copy from the user's real logs, replacing `/home/devlop13/.kengash/worktrees/chess-samurai/kg-<id>` with `{worktree}` (tests substitute the tmp path):
  - `flutter_test_assertion.txt`: `~/.kengash/runtime/logs/d24db74a-3.out` whole (the failing `samurai_theme_test.dart … [E]` block with `Expected: Color:<…red: 0.1020…>` / `Actual: Color:<…red: 0.9961…>`, then passing tests, then `Some tests failed.`).
  - `flutter_test_compile.txt`: the 2ddb11c5 run whose output holds `lib/domain/ai/ai_engine.dart:53:7: Error: Field 'scoreGuess' should be initialized` (find it with `grep -l scoreGuess ~/.kengash/runtime/logs/2ddb11c5-*.out`).
  - `flutter_analyze.txt`: `d24db74a-5-lint.out` followed by `d24db74a-5-lint.err`.
  - `pytest_failure.txt`: synthetic: 40 `PASSED` lines, a `___ test_retry ___` block with `>       assert retries == 3` / `E       assert 2 == 3` / `tests/test_retry.py:12: AssertionError`, then `FAILED tests/test_retry.py::test_retry - assert 2 == 3` and `1 failed, 40 passed in 0.31s`.

- [ ] **Step 2: Write the failing tests** (`tests/test_adapters_digest.py`, helper `load(name, worktree) -> str` substitutes `{worktree}`):
  - `test_a_flutter_assertion_keeps_the_failing_test_and_its_values`: text contains `[E]`, `red: 0.1020`, `red: 0.9961`, ends with `Some tests failed.`; `"CaptureDirector skip accepted" not in text`; headline starts ``"`flutter test` exit 1: "``.
  - `test_a_compile_error_names_its_file_and_line`: with `lib/domain/ai/ai_engine.dart` created under `cwd`: `(d.file, d.line) == ("lib/domain/ai/ai_engine.dart", 53)`; `"scoreGuess" in d.headline`.
  - `test_analyzer_rows_survive_and_pub_noise_goes`: `prefer_const_constructors`, `unnecessary_import` and `2 issues found` in text; `"available)" not in text`; with `lib/core/theme/samurai_theme.dart` created, `(d.file, d.line) == ("lib/core/theme/samurai_theme.dart", 55)`.
  - `test_pytest_failures_are_kept`: `E       assert 2 == 3` and `1 failed, 40 passed` in text; `(d.file, d.line) == ("tests/test_retry.py", 12)` when that file exists; `"PASSED" not in text`.
  - `test_without_markers_the_last_30_lines_stay`: 100 lines `line N`, exit 3 → text is lines 71–100; headline ``"`make check` exit 3: line 100"`` (*call*: with no marker the headline quotes the last line).
  - `test_the_digest_is_capped_and_says_where_the_rest_is`: 500 lines `error: n` → `len(text.splitlines()) == 61`, `len(text) <= 4100`, first line contains `error: 0`, last line `… 440 more lines; full output: <log>` (*call*: the count is the dropped marker-window lines).
  - `test_huge_output_is_fast`: 200,000 lines with one `error: boom` in the middle → `excerpt` under 1 s and `error: boom` in text.
  - `test_ansi_codes_and_long_lines_are_cleaned`: `"\x1b[31merror: red\x1b[0m"` → `error: red`; a 1,000-character marker line is cut to 300.
  - `test_paths_outside_the_worktree_are_not_locations`: `/usr/lib/x.py:3: error` → `d.file == ""`.
  - `test_section_fences_the_digest`: `section(d) == f"{d.headline}\n```text\n{d.text}\n```"`; a digest line starting with ```` ``` ```` gets a leading space.

- [ ] **Step 3: Run them.** `uv run pytest tests/test_adapters_digest.py -q` → fails on import.

- [ ] **Step 4: Implement `excerpt` and `section`** per the Global Constraints bounds and spec §3.2 markers. One pass over the lines builds the marker indexes, then windows merge in order; the location is the first `(?P<path>[\w./~-]+\.\w+):(?P<line>\d+)` match whose path, made relative to `cwd.resolve()` when absolute, exists under `cwd`.

- [ ] **Step 5: Run them.** Same command → PASS. Also `make lint`.

- [ ] **Step 6: Commit** with the adapters README naming `digest`: `feat(sp15): failure digest for check output`.

### Task 2: Shell checks report the digest

**Files:**
- Modify: `src/kengash_ai/model/steps.py` (`StepResult`), `src/kengash_ai/adapters/shell.py`
- Modify: `tests/test_adapters_core.py`, `docs/modules/adapters/README.md`, `docs/modules/model/README.md`

**Interfaces:**
- Consumes: Task 1 `excerpt`, `section`.
- Produces: `StepResult.check_output: str = ""`, set on a failing shell check to `section(digest)`; the finding is `Finding(severity="high", file=d.file, line=d.line, issue=d.headline, fix=f"fix the cause in Check output, then run {command}")`; `summary` stays `"<tests|lint> failed (exit <n>)"`.

- [ ] **Step 1: Replace `test_shell_failure_keeps_the_last_20_lines_even_when_not_utf8`** with `test_shell_failure_digests_the_output_even_when_not_utf8` (same non-UTF-8 script; assert the finding's issue starts with the backticked command and `exit 1`, `check_output` starts with that headline and holds the `error` line) and add `test_a_lint_failure_names_the_lint_command` (`test_cmd="true"`, `lint_cmd="echo 'warning: x' && exit 2"` → summary `lint failed (exit 2)`, fix ends ``run echo 'warning: x' && exit 2``) and `test_a_pass_has_no_check_output`.
- [ ] **Step 2: Run** `uv run pytest tests/test_adapters_core.py -q` → the new tests fail.
- [ ] **Step 3: Implement** the field and the shell change; `tail` stays only for timeouts.
- [ ] **Step 4: Run** the same tests, then `uv run pytest -q` → PASS (other tests reading the old finding text get updated to the new issue text).
- [ ] **Step 5: Commit** `feat(sp15): shell checks report a digest, not a tail`.

### Task 3: Settings, ticket section, state fields

**Files:**
- Modify: `src/kengash_ai/model/settings.py`, `src/kengash_ai/model/runtime.py`, `src/kengash_ai/model/documents.py`, `src/kengash_ai/model/__init__.py`, `src/kengash_ai/store/defaults/SETTINGS.md`, `src/kengash_ai/workflow.py` (`Approval` only)
- Modify: `tests/test_model_settings.py`, `tests/test_runtime.py`, `tests/test_documents.py`; READMEs of `model`, `store`, `workflow`

**Interfaces:**
- Produces: `Checks(turns: int = 2)` at `Settings.checks`; `SentBack(step: str, summary: str)`, `Checked(commit: str, step: str, summary: str)`; `TicketState.sent_back: SentBack | None = None`, `TicketState.checked: Checked | None = None`; `"blocked"` added to `TicketState.approval` and `workflow.Approval`; `TICKET_SECTIONS == ("Scope", "Acceptance", "Handoff", "Findings", "Check output", "Log")`.

- [ ] **Step 1: Write the failing tests:** `test_checks_turns_default_and_bounds` (default 2; `checks.turns: 0` loads; `-1` and `6` raise); `test_ticket_state_loads_old_files_and_round_trips_the_new_fields` (a state JSON without the fields loads with both `None`; one with `sent_back` and `checked` and `approval: blocked` round-trips); `test_check_output_is_saved_between_findings_and_log` (saved file has `## Findings` before `## Check output` before `## Log`; an empty section is left out like the others).
- [ ] **Step 2: Run** them → fail.
- [ ] **Step 3: Implement.** In `store/defaults/SETTINGS.md`, after `loop_start:` add `checks.turns: 2                # fix turns an editing step gets when kengash's checks fail after it; 0 = off (SP15)`.
- [ ] **Step 4: Run** `uv run pytest -q` → PASS.
- [ ] **Step 5: Commit** `feat(sp15): checks.turns, Check output section, sent_back and checked state`.

### Task 4: Prompts name the checks and why a step is back

**Files:**
- Modify: `src/kengash_ai/ops/prompts.py`, `src/kengash_ai/ops/steps.py` (`_request` only)
- Modify: `tests/test_ops_prompts.py`, `docs/modules/ops/README.md`

**Interfaces:**
- Consumes: Task 3 `SentBack`.
- Produces:
  - `Feedback(checks: str = "", sent_back: str = "", user: bool = False, editing: bool = False)` (frozen dataclass) passed as `feedback: Feedback = Feedback()` to `new_prompt` and `resumed_prompt`;
  - `checks_block(test_cmd: str, lint_cmd: str) -> str` ("" when both empty);
  - `sent_back_line(sent: SentBack, *, check: bool) -> str` (flattened, redacted, summary cut to 300);
  - `fix_prompt(check_output: str, *, turn: int, turns: int) -> str` (the headline is `check_output`'s first line; the rest goes under `## Check output`);
  - `check_log_line(at: datetime, verdict: str, summary: str) -> str` → `- <at:%Y-%m-%d %H:%M> · checks · kengash · shell/default · <verdict> · 0 · <summary>`.
- Block order, new prompt: Goal, Scope, Acceptance, Handoff, Findings, Check output (only `editing`), Checks, Diff stat. Resumed work step: Findings, Check output (only `editing`), Checks. Resumed review step: Handoff, Diff stat, Checks.
- Heads: new `f"{head}\n{told}"` plus `"\n" + sent_back` when set. Resumed: `Loop <n>, step <s>: <sent_back>` when set and not `user`; `Loop <n>, step <s>: <told>\n<sent_back>` for `user`; else today's.
- `_request` builds `Feedback(checks=checks_block(...), sent_back=sent_back_line(state.sent_back, check=resolved.kind_of(state.sent_back.step) == "check") if state.sent_back else "", user=state.sent_back is not None and state.sent_back.step == "user", editing=kind == "edit")`.

- [ ] **Step 1: Write the failing tests:** `test_new_prompts_name_the_checks`; `test_no_commands_no_checks_block`; `test_a_check_sent_back_head_replaces_the_instruction` (head exactly `Loop 3, step implement: run_tests sent this back: lint failed (exit 1). Fix every Finding below, then run the failing check.` and `## Check output` present); `test_a_review_sent_back_head_has_no_check_clause`; `test_the_users_answer_follows_the_instruction`; `test_reviewers_get_checks_but_not_check_output`; `test_sent_back_lines_are_flat_redacted_and_short` (a summary with a newline and `sk-ant-api03-…` comes out one line, redacted, ≤ 300 chars of summary); `test_fix_prompt_carries_the_headline_and_output`; `test_check_log_line`.
- [ ] **Step 2: Run** `uv run pytest tests/test_ops_prompts.py -q` → fail.
- [ ] **Step 3: Implement** in `prompts.py`; wire `_request`.
- [ ] **Step 4: Run** `uv run pytest -q` → PASS (update older prompt assertions only where a Checks block now appears).
- [ ] **Step 5: Commit** `feat(sp15): prompts name the checks and who sent a step back`.

### Task 5: Check output and sent_back written by the step loop

**Files:**
- Modify: `src/kengash_ai/ops/steps.py` (`_finish`)
- Modify: `tests/test_ops_steps.py`, `docs/modules/ops/README.md`

**Interfaces:**
- Consumes: Task 2 `StepResult.check_output`, Task 3 fields.
- Produces: in `_finish`, under the lock: `state.sent_back = None` first; a `check`-kind step sets `doc.sections["Check output"]` to `result.check_output` on fail and `""` on pass; when the verdict is `fail` and the decision is `workflow.Run`, `state.sent_back = SentBack(step=<step that ran>, summary=<output.summary>)`.

- [ ] **Step 1: Write the failing tests** (settings via `write_settings` with `checks.turns: 0`, `project.test_cmd: "echo 'error: boom' && exit 1"`, test-runner on `shell`, workflow `simple` = `[plan, implement, run_tests, review_code]` with `on_fail: {run_tests: implement, review_code: implement}`):
  - `test_a_failing_check_writes_check_output_and_sends_it_back`: after plan, implement, run_tests: Findings line starts ``- high · -:0 · `echo 'error: boom' && exit 1` exit 1: error: boom``; `Check output` starts with that headline; `state.sent_back == SentBack(step="run_tests", summary="tests failed (exit 1)")`; the next implement call's prompt contains `run_tests sent this back: tests failed (exit 1).`
  - `test_a_passing_check_clears_check_output`.
  - `test_the_next_step_consumes_sent_back` (after that implement passes, `state.sent_back is None`).
- [ ] **Step 2: Run** → fail. **Step 3: Implement.** **Step 4: Run** `uv run pytest -q` → PASS.
- [ ] **Step 5: Commit** `feat(sp15): record check output and the step that sent a ticket back`.

### Task 6: Checks inside the editing step

**Files:**
- Create: `src/kengash_ai/ops/checks.py`
- Modify: `src/kengash_ai/ops/steps.py` (`_step`, new `_verify`, `_Ran`)
- Modify: `tests/test_ops_steps.py`, `docs/modules/ops/README.md`

**Interfaces:**
- Consumes: Tasks 2–5.
- Produces:
  - `checks.wanted(resolved: Settings, ticket: Ticket, step: str) -> bool`: `checks.turns > 0`, a command set, and a `check`-kind step after `step` in `workflow.steps_for(resolved, ticket.workflow, hitl=...)`;
  - `checks.request(resolved: Settings, worktree: Path, log: Path) -> StepRequest` (role `test-runner`, empty prompt, output `review`, profile `read_only`, `calls.step_timeout`, both commands);
  - `_Ran.checked: str | None = None` (the summary when the last in-step check passed), `_Ran.hook_repaired: bool = False` (set by `_commit` on its repair turn, used in Task 7);
  - `_verify(job, ready, ran) -> JobEnd | None`, called in `_step` between `_call` and `_commit` for `edit` steps.
- `_verify` loop, turn 0..`turns`: name a log with `_next_log`; set `state.running` to `Running(role="test-runner", provider="shell", model=None, log=log)`; run the shell adapter; under the lock (stop if the ticket left the step) write or clear `Check output`, append `check_log_line`, journal `checks.end` (`step`, `turn`, `verdict`, `summary`, `duration_s`, `log`); pass → `ran.checked = summary`, return; timeout, last turn, or a moved ticket → return; else put `state.running` back on the step's role and resume the session with `fix_prompt` via `_resume` (a `network` error resumes once; `schema` or `empty` ends the turns keeping `ran.result`; other errors → `_call_failed`), add usage, replace `ran.result` keeping the session id, and loop.

- [ ] **Step 1: Write the failing tests** (settings as Task 5 but `checks.turns` default, `project.test_cmd: "test -f fixed.txt || { echo 'error: fixed.txt missing'; exit 1; }"`):
  - `test_checks_pass_first_time_with_no_fix_turn`: implement edits `fixed.txt`; one `checks.end` (turn 0, pass); Log has `· checks · kengash · shell/default · pass · 0 · tests passed`; codex called once for implement.
  - `test_a_failing_check_gets_a_fix_turn_in_the_same_loop`: first reply edits `a.txt`, the fix reply edits `fixed.txt`; codex's second call is a resume whose prompt has `fix turn 1 of 2` and `error: fixed.txt missing`; `checks.end` verdicts `[fail, pass]`; the step's commit holds `fixed.txt`; ticket at `run_tests`, loop 1; `Check output == ""`.
  - `test_when_fix_turns_run_out_run_tests_sends_it_back`: `checks.turns: 1`, both replies leave it failing → implement passes, `run_tests` fails, loop 2, Findings set.
  - `test_no_check_step_no_in_step_checks` and `test_checks_turns_zero_turns_them_off`: no `checks.end`, codex called once.
  - `test_a_network_error_in_a_fix_turn_resumes_once`.
  - `test_an_invalid_fix_reply_keeps_the_last_valid_one` (Review Focus 2): fix turn reply schema-invalid twice → ticket not failed, Handoff from the first reply.
  - `test_a_hanging_check_ends_the_in_step_checks` (Review Focus 3): monkeypatch `calls.step_timeout` to 1 s, `test_cmd: "sleep 5"` → one `checks.end` with verdict `timeout`, no fix turn.
  - `test_a_ticket_moved_during_checks_gets_no_fix_turn` (Review Focus 5): monkeypatch the shell adapter's `run` to park the ticket (`controls.park_ticket`) and return a fail → no resume call, status `in_queue/parked`.
- [ ] **Step 2: Run** → fail. **Step 3: Implement.** **Step 4: Run** `uv run pytest -q` and `make lint` → PASS.
- [ ] **Step 5: Commit** `feat(sp15): run the checks inside editing steps with fix turns`.

### Task 7: run_tests reuses a passing in-step result

**Files:**
- Modify: `src/kengash_ai/ops/steps.py` (`_step`, `_call`, `_commit`)
- Modify: `tests/test_ops_steps.py`, `docs/modules/ops/README.md`

**Interfaces:**
- Consumes: Task 6 `_Ran.checked`, `_Ran.hook_repaired`; Task 3 `Checked`.
- Produces: after `_commit`, when `ran.checked` and not `ran.hook_repaired`, `state.checked = Checked(commit=gitops.head(worktree), step=<step>, summary=ran.checked)`; in `_call`, after `_prepare`, a shell `check` step whose HEAD equals `state.checked.commit` with no changed files returns `_Ran` with `StepResult(output=ReviewOutput(verdict="pass", summary=f"{summary} (in {step}, same commit)", findings=[]), duration_s=0.0)` without running.

- [ ] **Step 1: Write the failing tests** (`test_cmd` also appends to a counter file outside the worktree: `echo x >> <tmp>/runs; test -f fixed.txt || …`):
  - `test_run_tests_reuses_a_passing_in_step_result`: `runs` has 1 line; run_tests Log line verdict `pass`; `step.end` for run_tests has `duration_s == 0`.
  - `test_run_tests_reruns_on_a_dirty_worktree_or_a_new_commit`.
  - `test_a_failing_in_step_result_is_never_reused` (turns run out → `runs` counts the run_tests run too).
  - `test_a_hook_repair_turn_disables_reuse` (set up the failing hook as `test_a_failing_hook_gets_one_repair_turn` does).
- [ ] **Step 2: Run** → fail. **Step 3: Implement.** **Step 4: Run** `uv run pytest -q` → PASS.
- [ ] **Step 5: Commit** `perf(sp15): run_tests reuses checks that passed on the same commit`.

### Task 8: A BLOCKED handoff stops the ticket

**Files:**
- Modify: `src/kengash_ai/workflow.py`, `src/kengash_ai/ops/prompts.py`, `src/kengash_ai/ops/steps.py` (`_finish`), `src/kengash_ai/ops/controls.py`, `src/kengash_ai/cli.py`
- Modify: `tests/test_workflow.py`, `tests/test_ops_steps.py`, `tests/test_ops_controls.py`, `tests/test_cli_controls.py`; READMEs of `workflow`, `ops`, `cli`

**Interfaces:**
- Produces:
  - `Outcome.blocked: str = ""`; `after()` on a pass with `blocked` → `Routed(Halt(NEEDS_APPROVAL, f"blocked: {blocked}", "blocked"), now)`, step unchanged, loop unchanged;
  - `approve(..., "blocked")`: an `edit`-kind step → `before(settings, progress)` (runs it again, same loop); otherwise `after(settings, progress, Outcome("pass"))`;
  - `prompts.blocked_line(handoff: str) -> str`: the text after `BLOCKED:` on the first line whose stripped form starts with it, stripped, cut to 160; `""` when none;
  - `_finish` passes `blocked_line(output.handoff)` for `WorkOutput` of `read` or `edit` steps;
  - `controls.approve_ticket(..., note: str | None = None)`: `note` on any approval but `blocked` → `UserError("--note answers a blocked ticket")`; `blocked` → `state.sent_back = SentBack(step="user", summary=records.one_line(note, "note") if note else "the user resolved what you were blocked on")`; `ticket.approved` carries `note`;
  - CLI `kengash approve <id> --note TEXT` (help: `Answer to the ticket's BLOCKED line; the next step reads it.`).
- [ ] **Step 1: Write the failing tests:** workflow `test_a_blocked_pass_halts_for_the_user`, `test_approving_a_blocked_edit_step_runs_it_again_in_the_same_loop`, `test_approving_a_blocked_plan_moves_on`; steps `test_a_blocked_plan_stops_the_ticket` (planner reply handoff `Files: a.py\nBLOCKED: the design assets need the user's claude.ai login` → status `in_process/needs_approval`, reason `blocked: the design assets need the user's claude.ai login`, `approval == "blocked"`, loop 1, `ticket.needs_approval` journaled) and `test_blocked_implement_commits_its_work_first`; controls `test_a_blocked_note_reaches_the_next_prompt`, `test_a_note_on_a_loop_cap_is_refused`; CLI `test_approve_takes_a_note`.
- [ ] **Step 2: Run** → fail. **Step 3: Implement.** **Step 4: Run** `uv run pytest -q` → PASS.
- [ ] **Step 5: Commit** `feat(sp15): a BLOCKED handoff stops the ticket for the user`.

### Task 9: agy may run the checks

**Files:**
- Modify: `src/kengash_ai/adapters/antigravity.py`, `tests/test_adapters_antigravity.py`, `docs/modules/adapters/README.md`

**Interfaces:**
- Produces: `GIT_READS = ("git status", "git diff", "git log", "git show")`; `OPERATORS = ("&&", "||", ";", "|", ">", "<", "`", "$(")`; `runnable(req: StepRequest) -> list[str]` (test then lint, set and operator-free); `edit_line(commands: Sequence[str]) -> str`; on `edit_worktree` without bypass: with `runnable` non-empty, `--settings` allows `["read_file(*)", *[f"command({c})" for c in [*runnable, *GIT_READS]]]` and the prompt ends with `edit_line([...runnable, ...GIT_READS])` (exact text in spec §3.5, commands backticked); with none, today's `EDIT_LINE` and `READ_ALLOW`.
- [ ] **Step 1: Write the failing tests:** `test_edit_steps_may_run_the_checks_and_git_reads` (flutter commands: exact allow list and line), `test_operator_commands_are_left_out` (`test_cmd="uv run pytest && echo"`, `lint_cmd="ruff check"` → only `command(ruff check)` plus git reads), `test_without_commands_the_old_line_stays`, `test_resumed_edit_turns_carry_the_line_too`.
- [ ] **Step 2: Run** → fail. **Step 3: Implement.** **Step 4: Run** `uv run pytest tests/test_adapters_antigravity.py -q` → PASS.
- [ ] **Step 5: Live probe** (spends a little agy quota; ask the user first): in an empty temp git repo, `agy -p 'Run this terminal command and report its output: echo kengash-probe one' --mode accept-edits --output-format stream-json --settings '{"permissions":{"allow":["read_file(*)","command(echo kengash-probe)"]}}'` → a `run_command` step with state `DONE`; the same with `ls` asked → denied. Record the result in the adapters README.
- [ ] **Step 6: Commit** `feat(sp15): agy implementers may run the checks and read-only git`.

### Task 10: Skills

**Files:**
- Modify: `src/kengash_ai/roles/implement/SKILL.md`, `src/kengash_ai/roles/plan/SKILL.md`, `skills/loop/references/events.md`
- Modify: `tests/test_ops_skills.py`, `docs/modules/roles/README.md`

- [ ] **Step 1: Write the failing test** `test_role_skills_carry_the_sp15_rules`: implement mentions `Checks`, `checks not run`, `Check output`, `BLOCKED:`; plan mentions `BLOCKED:`; both pass the existing cap checks.
- [ ] **Step 2: Edit the skills** with spec §3.7 and §3.8 wording (`BLOCKED:` only for something the user must supply or decide, never for checks). Loop events row for `needs_approval`: a `blocked` gate quotes the BLOCKED line and asks; on an answer, `kengash approve <id> --note "<answer>"`.
- [ ] **Step 3: RED/GREEN the wording** per `docs/conventions/skills.md` with the haiku dry-run micro-test (a sent-back prompt and a login-only scope; the GREEN reply runs the named check and writes `BLOCKED:`), then `uv run kengash skills lint`.
- [ ] **Step 4: Run** `uv run pytest -q` → PASS. **Step 5: Commit** `feat(sp15): implement and plan skills know the checks and BLOCKED`.

### Task 11: Timeline shows check runs

**Files:**
- Modify: `src/kengash_ai/ops/views.py` (`_timeline_row`), `src/kengash_ai/ui/static/views/ticket.js`
- Modify: `tests/test_ops_views.py`; READMEs of `ops`, `ui`

- [ ] **Step 1: Write the failing test** `test_check_runs_show_on_the_timeline_but_not_in_the_chain`: a `checks.end` event → a `TimelineStep(kind="checks.end", note="fail · lint failed (exit 1) · turn 1")`; the chain's run count for `implement` unchanged.
- [ ] **Step 2: Implement**; `ticket.js` labels the row `checks` (`r.kind.replace("ticket.", "").replace(/\.end$/, "")`) and colours a `fail` note red.
- [ ] **Step 3: Run** `uv run pytest -q` → PASS. **Step 4: Commit** `feat(sp15): the timeline shows check runs`.

### Task 12: Contract docs

**Files:**
- Modify: `docs/superpowers/specs/2026-10-22-kengash-design.md` (§4.4 template, §4.6 `checks.turns`, §5 `blocked` gate, §6 `approve --note`, §6.1 `checks.end`, §7.1 in-step checks and reuse), `docs/superpowers/specs/2026-10-22-sp3-engine-design.md` (§8.2 prompt blocks, sent-back head, fix prompt), `docs/conventions/memory-files.md` (`## Check output` row: kengash, 62 lines), `docs/architecture.md` (SP15 row; `adapters`, `ops`, `workflow` status), `AGENTS.md` (status line; ≤ 100 lines)
- [ ] **Step 1: Edit** each as listed, in the spec's words. **Step 2: Run** `make check` → green. **Step 3: Commit** `docs(sp15): contract and architecture`.

### Task 13: Critical review and replay

- [ ] **Step 1:** Review every change against spec §1–§3 (superpowers:requesting-code-review), fix what it finds, `make check` green.
- [ ] **Step 2:** With the user's go-ahead (spends quota), install the branch build and rerun a chess-samurai ticket (`kengash run <id>`); confirm in its Log and Timeline: `checks` rows inside implement, Findings naming the failing test or lint row, `run_tests` reusing a pass, and for d24db74a-like scope a `blocked` gate.
