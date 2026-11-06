# SP12 Worker Reliability and Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- A worker step never loses finished work to a network error.
- Transient errors are retried, then sent to the fallback.
- Every running worker can be watched live: `wait` progress, `kengash ps`, `kengash logs -f` (a background task in Claude Code), and the UI's Live tab.
- Projects get test and lint checks that actually run.

**Architecture:**
- Adapters switch claude and agy to `stream-json`. They parse the last result event with a tolerant parser that still reads today's single-object output, so the existing fake CLIs keep working.
- They classify the CLI's own error field into the new `network` kind, and a valid structured output wins over a CLI error.
- `run_process` writes a `<log>.ts` stamp per stdout line.
- `ops.activity` turns a ticket's logs plus its journal into readable lines. `ops.progress` summarises running tickets. The CLI (`wait`, `ps`, `logs`) and the UI (SSE `live`, Live tab, activity cells) share both.
- `ops.hygiene` holds command detection and the doctor fixes.

**Tech Stack:** Python 3.12+, Pydantic, Typer, FastAPI (SSE), vanilla JS modules, pytest, node (static UI tests), headless Chrome over CDP.

**Spec:** `docs/superpowers/specs/2026-11-06-sp12-worker-reliability-design.md`

## Global Constraints

- Exact copy:
  - network resume prompt: `Your last turn was cut off by a network error. Your edits are kept; finish the step and reply.`
  - retry note: `The worktree already holds changes from a failed attempt; review them and finish the step.`
  - failure line: `<kind>: <first line of detail>; log: <path>`, plus `; work kept in <worktree> (N files changed)` for an editing step with changes; at most 300 characters, shortening only the detail.
  - progress line: `<id> <step>→<provider>/<model> <elapsed> · active <age> ago · <N> files changed · <action>`, plus ` · quiet` at 600 s or more without activity, plus ` · worker gone` when the worker is dead.
  - `ps`: those lines, or `nothing running`. `ps --line`: `kg: <N> running · <first id> <step>→<provider> <elapsed> <action>`, or `kg: nothing running`.
  - `logs`: one line per event, `HH:MM:SS <text>` (local time; `--:--:--` when unknown).
  - token cap: `token cap: <used:,> of <max:,> used; approve with: kengash approve <id> --tokens N`.
  - doctor:
    - `project <slug> has no test command; detected: <cmd>; run: kengash doctor --fix`, or `…; set project.test_cmd`;
    - `<scope> still has the old default <key>; run: kengash doctor --fix`;
    - `<scope>: agent <role> has no fallback` (an info line).
- Values:
  - `QUIET_S = 600`;
  - `wait --timeout` default 300;
  - the activity tail reads the last 64 KiB;
  - the worktree status cache lasts 60 s;
  - the `tokens.per_ticket_max` default is 1_000_000;
  - old defaults: `tokens.per_ticket_max: 250000`, a doc-writer without `fallback`, the key `fallback_on_rate_limit`.
- `network` matches, case-insensitive, after `auth` and `rate_limit`:
  - `connection reset`, `connection refused`, `broken pipe`, `ECONNRESET`, `\bEOF\b`;
  - `TLS handshake`, `no such host`, `temporary failure in name resolution`, `network is unreachable`, `stream error`;
  - `\b50[0234]\b`, `UNAVAILABLE`, `\bINTERNAL\b`, `overloaded`.
- Hard rules:
  - each `src/kengash_ai/<module>` change updates `docs/modules/<module>/README.md` in the same commit;
  - the system spec changes first;
  - skills stay at or under 400 words and 80 lines (whole file);
  - no API keys in workers;
  - no browser dialogs; UI values go through `html`.

## Review Focus

1. agy reports `ERROR` with a structured output that fails the schema: it stays an error, never a success. Test `test_an_invalid_output_with_an_error_stays_an_error`, Task 2.
2. A network error on a new session the CLI never created (no session id): the retry runs the request again rather than resuming a missing session. Test `test_network_error_without_a_session_retries_fresh`, Task 5.
3. `auth` is never retried, and a fallback chain used up after a network error fails with the worktree line. Tests `test_auth_is_never_retried` and `test_network_then_fallback_then_failure_names_the_worktree`, Task 5.
4. One ticket whose steps ran on claude, then agy, then codex: `logs` parses each log with its own provider, in time order. Test `test_activity_reads_each_provider_in_order`, Task 8.
5. A step whose worker died shows `· worker gone`, not a healthy line. Test `test_progress_marks_a_dead_worker`, Task 9.

---

## Milestone 1: Reliability

### Task 0: Contract first
**Files:** `docs/superpowers/specs/2026-10-22-kengash-design.md`
- [ ] **Step 1:** Edit per SP12 §6:
  - §4.6: `fallback_on_error` (the old key is still read), `tokens.per_ticket_max: 1000000`, the doc-writer `fallback: [claude/sonnet]`.
  - §5 item 5: `network` and a valid output winning.
  - §6:
    - `wait --timeout 300` and its progress lines;
    - the rows `kengash ps [--line]` and `kengash logs ID [-f]`;
    - doctor's project-command and old-default checks;
    - `run_tests` runs test, then lint.
  - §7.2: stream-json for claude and agy, and the session id from the first event.
- [ ] **Step 2:** Run `make docs` (passes), then commit `docs(sp12): system spec contract`.

### Task 1: The `network` kind and a CLI warning
**Files:** `model/steps.py` (`ErrorKind` gains `"network"`; `StepResult.warning: str = ""`), `adapters/base.py` (`_NETWORK`, used by `classify`), `tests/test_adapters_core.py`, docs model+adapters.
- [ ] **Step 1:** Write failing tests:
  - `test_classify_network`, parametrized over 6 samples including the evidence line `read tcp …: read: connection reset by peer`;
  - `test_auth_and_rate_limit_win_over_network`, e.g. `429 … connection reset` gives `rate_limit`.
- [ ] **Step 2:** FAIL, then implement, then PASS with `uv run pytest tests/test_adapters_core.py -q`, then commit `feat(sp12): network error kind`.

### Task 2: agy streams, keeps valid output, reads its own error
**Files:**
- Create `adapters/stream.py`:
  - `lines(text) -> list[dict]`: JSON objects, one per line; non-JSON lines are skipped.
  - `result(text, *, key: str, value: str) -> dict | None`: the last event with `event[key] == value`. When none is found, the whole text parsed as one object.
- `adapters/antigravity.py`:
  - argv `--output-format stream-json`;
  - parse uses `stream.result(stdout, key="event", value="result")["result"]`, falling back to the single object;
  - the session id is the `init` event's `conversation_id`;
  - `recover_session(log)` reads it from the `init` event;
  - classify on `data["error"]` plus stderr, never on `response`;
  - status ≠ SUCCESS with a fresh, schema-valid `structured_output` → success with `warning` set to `data["error"]`;
  - no result event → classify stderr plus the last event's error text, never `empty` when stderr is non-empty.
- Fixtures in `tests/fakes/fixtures/agy/`: `stream-ok.jsonl` (the 2026-11-06 probe, paths scrubbed) and `stream-error-valid.jsonl` (shaped like `7add8c2e-4.out`).
- Tests: `tests/test_adapters_antigravity.py`. Docs: adapters.

- [ ] **Step 1:** Write failing tests:
  - `test_stream_ok_parses_the_result`
  - `test_error_with_a_valid_output_is_a_success_with_a_warning`: output.summary is `Rebrand core package and UI to Chess Samurai`; warning contains `connection reset`; error is None.
  - `test_an_invalid_output_with_an_error_stays_an_error`
  - `test_the_error_field_is_classified_not_the_response`: a response saying "quota exceeded" with error `connection reset` gives `network`.
  - `test_recover_session_reads_init`
  - `test_no_result_classifies_stderr`
  - `test_the_old_single_object_still_parses`
- [ ] **Step 2:** FAIL, then implement, then PASS with `uv run pytest tests/test_adapters_antigravity.py -q`, then commit `feat(sp12): agy streams and keeps valid output`.

### Task 3: claude streams
**Files:**
- `adapters/claude.py`:
  - argv `--output-format stream-json --verbose`;
  - parse the last `{"type":"result"}` (or the single object);
  - the session is the result's `session_id`, else the `system/init` event's;
  - `recover_session(log)` reads `system/init`;
  - `is_error` with a schema-valid `structured_output` → success with `warning` (spec §3.1).
- Fixture `tests/fakes/fixtures/claude/stream-ok.jsonl` (from the 2026-11-06 probe, scrubbed).
- Tests: `tests/test_adapters_claude.py`.

- [ ] **Step 1:** Write failing tests: `test_stream_ok_parses_the_result`, `test_recover_session_reads_init`, `test_the_old_single_object_still_parses`, `test_argv_streams` (`--verbose` present), `test_error_with_a_valid_output_is_a_success`.
- [ ] **Step 2:** FAIL, then implement, then PASS with `uv run pytest tests/test_adapters_claude.py tests/test_adapters_codex.py -q`.
- [ ] **Step 3:** Run `uv run pytest -q -x`. The fake CLIs' single-object replies still parse. Commit `feat(sp12): claude streams`.

### Task 4: `fallback_on_error` and `calls` network retry
**Files:**
- `model/settings.py`: `fallback_on_error: bool = True`. A `model_validator(mode="before")` maps a present `fallback_on_rate_limit` onto `fallback_on_error` when that key is absent; the old field is dropped from the model.
- `store/defaults/SETTINGS.md`: the key renamed.
- `ops/calls.py`: `network` gets one `repair` with the network prompt, then the result is returned.
- `ops/prompts.py`: `NETWORK_PROMPT`.
- Tests: `tests/test_model_settings.py`, `tests/test_ops_calls.py`.

- [ ] **Step 1:** Write failing tests:
  - `test_old_fallback_key_is_read`
  - `test_both_keys_refused`: `fallback_on_rate_limit` and `fallback_on_error` together fail with `settings: use fallback_on_error only`.
  - `test_calls_resume_once_on_network`
- [ ] **Step 2:** FAIL, then implement, then PASS with `uv run pytest tests/test_model_settings.py tests/test_ops_calls.py tests/test_settings.py -q`, then commit `feat(sp12): fallback_on_error; calls retry network once`.

### Task 5: Steps retry network, fall back, keep the session
**Files:**
- `ops/steps.py`:
  - in `_call`:
    - `network` → one `_repair(…, NETWORK_PROMPT)`, which runs `_again` when there is no session;
    - then `_fallback` when `fallback_on_error`;
    - then `_fail`;
  - `rate_limit` uses `fallback_on_error` too;
  - the commit-hook turn (`_commit`) handles `network` the same way, as one resumed turn;
  - on any failure, `result.session_id` is stored in `doc.meta.sessions[role]` before `_fail`.
- Tests: `tests/test_ops_steps.py`, which queues fake replies with the network error text.

- [ ] **Step 1:** Write failing tests:
  - `test_network_error_resumes_once_then_passes`
  - `test_network_error_without_a_session_retries_fresh`
  - `test_network_then_fallback_then_failure_names_the_worktree`: the agent's fallback is used after the second network error; when it fails too, the ticket fails.
  - `test_auth_is_never_retried`
  - `test_a_failed_call_keeps_its_session`: the ticket's `sessions.implementer.id` equals the CLI's session.
  - `test_commit_hook_turn_survives_a_network_error`
- [ ] **Step 2:** FAIL, then implement, then PASS with `uv run pytest tests/test_ops_steps.py tests/test_lifecycle.py -q`, then commit `feat(sp12): steps retry network errors and fall back`.

### Task 6: Failures say where the work is; running state is exact
**Files:**
- `ops/calls.py`: `failure(provider, request, result, *, worktree: Path | None, changed: int) -> str` per Global Constraints.
- `gitops.py`: `changed_files(worktree) -> list[str]` (`git status --porcelain`, paths).
- `ops/steps.py`:
  - every new attempt sets `state.running.log`;
  - `state.running` is cleared on step end and on failure;
  - an editing step whose worktree has changes at `_prepare` gets the retry note prepended to its prompt.
- `workflow.py`: the token-cap reason per Global Constraints (with `{:,}`).
- Tests: `tests/test_ops_calls.py`, `tests/test_ops_steps.py`, `tests/test_workflow.py`, `tests/test_gitops.py`.

- [ ] **Step 1:** Write failing tests:
  - `test_failure_line_is_short_and_names_the_worktree`: a 2,000-character JSON detail gives at most 300 characters, ending `(3 files changed)`.
  - `test_running_log_follows_each_attempt_and_clears`
  - `test_a_retry_over_changes_gets_the_note`
  - `test_token_cap_reason_names_the_approval`
- [ ] **Step 2:** FAIL, then implement, then PASS with `uv run pytest -q`, then commit `feat(sp12): failures name the worktree; running state is exact`.
- [ ] **Step 3:** M1 review against spec §3: fix, then ledger.

## Milestone 2: Visibility

### Task 7: Stamped logs
**Files:** `adapters/process.py`. stdout goes through a pipe that a reader thread drains: it writes each line to `log`, flushing per line, and an ISO-UTC stamp line to `log.with_suffix(".ts")`. `ProcessResult` is unchanged. Tests: `tests/test_adapters_core.py`.
- [ ] **Step 1:** Write failing tests:
  - `test_stdout_lines_get_stamps`: `sh -c 'echo a; sleep 0.2; echo b'` gives 2 stamps, the second at least 0.15 s later.
  - `test_timeout_and_interrupt_still_end_the_group`: the existing tests stay green.
- [ ] **Step 2:** FAIL, then implement, then PASS with `uv run pytest tests/test_adapters_core.py tests/test_worker.py -q`, then commit `feat(sp12): stamped worker logs`.

### Task 8: `ops.activity`
**Files:** create `ops/activity.py`:
- `Activity(ts: datetime | None, kind: Literal["step","read","edit","run","reply","error","status"], text: str)`.
- `parse(text, stamps) -> list[Activity]`. The provider is told apart by its events:
  - agy: `event` key; `step_update` events with a `tool_name` ending `DONE`;
  - claude: `type` `assistant` with `tool_use` (`Read`/`Grep`/`Glob` → read, `Edit`/`Write`/`MultiEdit` → edit, `Bash` → run);
  - codex: `item.completed` with `command_execution` → run, `file_change` → edit, `agent_message` → reply.

  Targets are shown relative to the worktree.
- `ticket(paths, slug, ticket_id) -> list[Activity]`: the journal's `step.start`, `step.end` and status events for the ticket, merged by time with every `<id>-<n>.out` log of it, each read from its last 64 KiB.
- `follow(paths, slug, ticket_id, *, poll_s=1.0) -> Iterator[Activity]`: new lines until the ticket leaves a running sub-status, then a final `status` line.

Tests: `tests/test_ops_activity.py`, using the Task 2/3 fixtures plus a codex fixture. Docs: ops.

- [ ] **Step 1:** Write failing tests:
  - `test_agy_actions` (a read of `a.py`);
  - `test_claude_actions` (a Read);
  - `test_codex_actions`;
  - `test_activity_reads_each_provider_in_order`;
  - `test_follow_ends_with_the_ticket`.
- [ ] **Step 2:** FAIL, then implement, then PASS with `uv run pytest tests/test_ops_activity.py -q`, then commit `feat(sp12): worker activity from stream logs`.

### Task 9: `ops.progress`
**Files:** create `ops/progress.py`:
- `Progress(id, project, step, provider, model, elapsed_s, alive: bool, active_s: float | None, action: str, changed: int, quiet: bool)`.
- `running(paths, slugs) -> list[Progress]`:
  - tickets in `in_process` at a running sub-status;
  - `elapsed_s` from their last `step.start`;
  - `alive` from the worker record (pid and a heartbeat within `lifecycle.DEAD_AFTER_S`);
  - `active_s` from the newest mtime of the running log and the changed files;
  - `action` from the last activity line;
  - `changed` from `gitops.changed_files`, cached for 60 s per worktree when no file was written in that time.
- `line(p) -> str` per Global Constraints.

Tests: `tests/test_ops_progress.py`. Docs: ops.

- [ ] **Step 1:** Write failing tests:
  - `test_progress_line`, exact format;
  - `test_progress_marks_quiet`;
  - `test_progress_marks_a_dead_worker`;
  - `test_progress_counts_worktree_changes`.
- [ ] **Step 2:** FAIL, then implement, then PASS, then commit `feat(sp12): running ticket progress`.

### Task 10: CLI `wait` progress, `ps`, `logs`
**Files:**
- `ops/waiting.py`: `WaitResult.progress: list[Progress]`, filled on timeout.
- `cli.py`:
  - the `wait` default is 300; on exit 3 it prints the progress lines (capped at 5) on stdout before the stderr timeout line;
  - `ps [-p] [--line] [--json]`;
  - `logs ID [-f] [--json]` (`-f` streams `activity.follow` with `typer.echo` and flush).
- Tests: `tests/test_cli_progress.py`. Docs: cli+ops.

- [ ] **Step 1:** Write failing tests:
  - `test_wait_timeout_prints_progress`
  - `test_ps_lines_and_line_mode`
  - `test_ps_nothing_running`
  - `test_logs_prints_history`
  - `test_logs_follow_ends`
- [ ] **Step 2:** FAIL, then implement, then PASS with `uv run pytest tests/test_cli_progress.py tests/test_cli_loops.py -q`, then commit `feat(sp12): wait progress, kengash ps and logs`.

### Task 11: Loop skill: background tasks
**Files:**
- `skills/loop/SKILL.md`:
  - one sentence in step 3: "read `references/background.md` when your shell can run a command in the background";
  - the step 4 wording: exit 3 prints progress lines, which you show the user, then run `wait` again.
- Create `skills/loop/references/background.md` with the spec §4.4 instructions:
  - `kengash logs <id> -f` per started ticket, as a background task;
  - `kengash wait` in the background, handling events when it ends.
- Update `evals/loop/one-ticket.yaml` notes only.

- [ ] **Step 1:** Run `uv run kengash skills lint`: clean, at most 400 words. Commit `feat(sp12): loop watches workers as background tasks`.

### Task 12: UI data: live SSE and activity
**Files:**
- `ops/views.py`:
  - `Session` gains `active_s`, `action`, `changed`, `quiet`, from `progress`;
  - `TicketView` gains `running: Progress | None` and `in_progress: list[str]` (uncommitted files).
- `ui/app.py`: `GET /api/tickets/{id}/live` streams `event: activity` (JSON `Activity`) from `activity.ticket` history, then `follow`, ending with `event: done`.
- Tests: `tests/test_ops_views.py`, `tests/test_ui_app.py`.

- [ ] **Step 1:** Write failing tests:
  - `test_sessions_carry_activity`
  - `test_ticket_view_lists_in_progress_files`
  - `test_live_streams_history_then_done`: a finished ticket gives its lines and then `done`.
- [ ] **Step 2:** FAIL, then implement, then PASS, then commit `feat(sp12): live activity API`.

### Task 13: UI: Live tab, activity cells, pulsing cards
**Files:**
- `ui/static/views/ticket.js`: a `live` tab first when `data.running`. Its rows show time, a kind icon and the text; it opens an `EventSource`, which `bind` closes on leave; it follows the newest row unless the user scrolled up; its header is pulsing, with the step, CLI/model, elapsed time and files.
- `views/overview.js`:
  - an activity cell (`active <age> ago · <N> files · <action>`, `.danger` when quiet);
  - a row click opens `#/ticket/<id>?tab=live`.
- `views/board.js`: a `.pulse` dot on running cards.
- `views/ticket.js`: the changes tab gains an "In progress" list.
- `app.css`: pulse keyframes, respecting `prefers-reduced-motion`.
- `api.js`: an `stream(path, onEvent)` helper.
- Tests: `tests/test_ui_static.py`, with node tests for a pure `activityRow(a)` formatter.

- [ ] **Step 1:** Write failing tests: `test_activity_row_formats`; static checks that `EventSource` is closed in the ticket view, plus `prefers-reduced-motion`.
- [ ] **Step 2:** FAIL, then implement, then PASS. Check with CDP at 360 and 1440 px on a demo store with a stream log: no overflow, the tab is reachable by keyboard. Then commit `feat(sp12): Live tab and activity in the UI`.
- [ ] **Step 3:** M2 review against spec §4.

## Milestone 3: Setup

### Task 14: `run_tests` runs test then lint
**Files:** `adapters/shell.py`. It runs `test_cmd`, then `lint_cmd`, skipping an empty one; both empty gives the existing `crash: set project.test_cmd`. The first failure is the verdict, and its finding names the command and the tail of its output. Tests: `tests/test_adapters_core.py` or the shell tests.
- [ ] **Step 1:** Write failing tests:
  - `test_lint_runs_after_tests`
  - `test_lint_failure_fails_the_step`
  - `test_only_lint_set`
- [ ] **Step 2:** FAIL, then implement, then PASS, then commit `feat(sp12): run_tests runs lint too`.

### Task 15: `ops.hygiene`: detection, init, doctor
**Files:** create `ops/hygiene.py`:
- `detect_commands(repo) -> tuple[str, str]`, using the spec §5.1 table.
- `apply_checks(paths, slug, test, lint) -> list[str]`. It writes the empty `project.*` keys, switches `agents.test-runner.on` to true, and inserts `run_tests` after `implement` in `standard` and `critical` with `on_fail: {run_tests: implement}`, when they are missing. It is one validated `settings.set_values` save and returns the changed keys.
- `old_defaults(paths, scope) -> list[str]`, and `fix_old_defaults(paths, scope)`, which keeps comments.
- `checks(paths, fix) -> list[Problem]`: the doctor lines per Global Constraints.

`projects.init_project` calls `detect_commands` and `apply_checks` for a new project. `projects.doctor` appends `hygiene.checks`.

Tests: `tests/test_ops_hygiene.py`. Docs: ops.

- [ ] **Step 1:** Write failing tests:
  - `test_detects`, parametrized over flutter, dart, uv, node, go, rust and none;
  - `test_init_writes_commands_and_the_checks_step`;
  - `test_doctor_reports_and_fixes_old_defaults_keeping_comments`;
  - `test_fix_never_touches_a_changed_value`;
  - `test_agents_without_fallback_are_info`.
- [ ] **Step 2:** FAIL, then implement, then PASS with `uv run pytest tests/test_ops_hygiene.py tests/test_cli_projects.py -q`, then commit `feat(sp12): detect project checks; doctor fixes old defaults`.

### Task 16: Defaults and agy permissions
**Files:** `store/defaults/SETTINGS.md`: `tokens.per_ticket_max: 1000000`, and the doc-writer with `fallback: [claude/sonnet]`. `model/settings.py`: the `Tokens` default is 1_000_000.
- [ ] **Step 1:** Live probe, in the scratchpad. `agy -p "read ../outside.txt and reply" --mode accept-edits --settings '<json>'`, trying `{"permissions":{"allow":["read_file(*)"]}}`. Ledger the key that works.
- [ ] **Step 2:** If one works, editing steps in `adapters/antigravity.py` pass `--settings` with that allow. Test `test_edit_steps_allow_reads`. If none works, ledger a ruling and keep the repair turn.
- [ ] **Step 3:** Tests for the defaults: `test_default_token_cap`, `test_seed_doc_writer_fallback`. PASS, then commit `feat(sp12): defaults and agy read permissions`.

### Task 17: Docs, live smoke, release notes
**Files:**
- `docs/architecture.md`: the SP12 row; `activity`, `progress`, `hygiene`.
- `AGENTS.md`: the status now counts 12 sub-projects; commands `ps|logs`.
- `CHANGELOG.md`.
- `skills/README.md` if needed.
- `tests/live/test_live_smoke.py`: `test_streams_give_activity` (one claude step and one agy step: `kengash logs` shows at least one read).

- [ ] **Step 1:** Write the docs. `make check` passes. `make live -k "streams or lease or end_to_end"` passes on claude and agy.
- [ ] **Step 2:** Rerun the evals: `kengash skills eval loop --agent claude`.
- [ ] **Step 3:** Commit. Then the final whole-branch review (requesting-code-review), one fix pass, and finishing-a-development-branch.
