# SP16 Shared memory and parallel tickets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Workers see and grow the project's memory, and independent tickets run at once while main stays green.

**Architecture:** Memory digest built in `memory`, injected by `ops/prompts` into new sessions. Decisions are captured deterministically: on plan approval, and from worker replies when the ticket merges. Path claims move from "every in_process ticket" to "the editing phase only" (`workflow.edit_phase`, `lifecycle.holds_paths`). Jobs wait in `waiting_paths`. Planners narrow touches to exact files. Merges serialize on a per-project lock and recheck a moved base. `merge.mode` defaults to `auto`.

**Tech Stack:** Python 3.12+, pydantic, typer, pytest with fake CLIs (`tests/fakes`), uv, ruff, mypy, import-linter.

**Spec:** `docs/superpowers/specs/2026-11-07-sp16-memory-parallel-design.md`

## Global Constraints

- `adapters` and `workflow` import only `model`; `scheduler` stays pure (model only); `memory` imports model, store, journal, settings.
- A change to `src/kengash_ai/<module>` updates `docs/modules/<module>/README.md` in the same commit.
- Only `kengash` writes store files; every memory write is journaled (`memory.write`) and committed.
- Strict output schemas: every property required, `additionalProperties: false`.
- Digest caps: PROCESS 3,000 chars, decisions 2,500, memory 1,500; proposals ≤ 3 per reply, ≤ 6 per ticket; files 1–40; `PATH_POLL_S = 5`.
- Docs ≤ 150 lines (specs, plans exempt); skills ≤ 80 lines, ≤ 400 words.
- TDD: every behaviour gets a test that fails first.

## Review Focus

- A worker reply from an older CLI without `files`/`decisions` must still parse: pydantic defaults `[]`.
- Two jobs entering the editing phase on overlapping files at the same moment: exactly one proceeds (check and move happen together under the project lock).
- A rebase that moved nothing must not rerun checks; a merge whose checks fail must leave main untouched and the ticket back at implement.
- Unsafe planner `files` (absolute, `..`, empty, > 40) must leave touches unchanged.
- Fuzzy dedupe must not merge different decisions that share a prefix.

---

### Task 1: Model and schema

**Files:** `src/kengash_ai/model/steps.py`, `model/documents.py`, `model/runtime.py`, `model/settings.py`, `model/__init__.py`, `store/defaults/SETTINGS.md`, `ops/prompts.py` (`output_kind`); tests `tests/test_model_steps.py`, `test_documents.py`, `test_model_settings.py`, `test_runtime.py`, `test_ops_prompts.py`.

**Produces:** `Decision(decision: str, why: str, rejected: str = "")`; `WorkOutput.decisions: list[Decision] = []`; `PlanOutput(WorkOutput)` with `files: list[str] = []`; `OutputKind = Literal["work","plan","review","compact"]`; `OUTPUT_SCHEMAS["work"]` = strict `{summary, handoff, decisions}`, `["plan"]` = strict `{summary, handoff, files, decisions}`, decision item strict `{decision, why, rejected}`. `TICKET_SECTIONS = ("Scope","Acceptance","Handoff","Findings","Decisions","Check output","Log")`. `PLAN_SECTIONS` gains `"Lasting decisions"` after `"Decisions"`. `SUB_STATUSES[in_process]` gains `"waiting_paths"`. `TicketState.waiting_on: str = ""`. `Merge.mode` default `"auto"`; shipped SETTINGS.md `merge.mode: auto`. `prompts.output_kind`: read → `"plan"`.

- [ ] Tests first:
  - `test_plan_output_parses_files_and_decisions`;
  - `test_work_output_without_decisions_still_parses`;
  - `test_output_schemas_are_strict` (extend to plan and nested decision);
  - `test_ticket_sections_include_decisions_before_check_output`;
  - `test_plan_sections_include_lasting_decisions`;
  - `test_waiting_paths_is_an_in_process_status`;
  - `test_merge_mode_defaults_to_auto` (model and shipped file);
  - `test_read_steps_reply_with_plan_output`.
- [ ] Run them and see them FAIL. Implement. Run `uv run pytest tests/test_model_steps.py tests/test_documents.py tests/test_model_settings.py tests/test_runtime.py tests/test_ops_prompts.py -q` and see PASS.
- [ ] Update `docs/modules/model/README.md` and the ops and store READMEs. Commit `feat(sp16): model for decisions, plan output, waiting_paths, auto merge`.

### Task 2: Memory digest in every new session

**Files:** `src/kengash_ai/memory.py`, `ops/prompts.py`, `ops/steps.py` (`_request`), `ops/reviews.py` (`_decisions` → digest); tests `tests/test_memory.py`, `test_ops_prompts.py`, `test_ops_steps.py`, `test_ops_reviews.py`.

**Produces:**
- `memory.digest(paths: StorePaths, slug: str) -> str`: body text without a heading; `""` when empty. Parts: `Process:` + PROCESS.md from its first `## `; `Decisions:` + `[slug]`/`[global]` lines; `Preferences:` + MEMORY lines as `- <Section>: <text>`. Caps per spec; the oldest go first; note `… N older lines in <file>`; redacted.
- `prompts.MEMORY_LEAD` (spec §3.1 text); `new_prompt(..., memory: str = "")` puts block `("Memory", f"{MEMORY_LEAD}\n{memory}")` first when memory is set; `plan_review_prompt` takes the digest in place of decisions.

- [ ] Tests first:
  - `test_digest_orders_process_decisions_memory`;
  - `test_digest_keeps_project_and_global_decisions_only`;
  - `test_digest_drops_oldest_over_cap_with_note`;
  - `test_digest_empty_store_is_empty`;
  - `test_new_prompt_puts_memory_first`;
  - `test_resumed_prompt_has_no_memory`;
  - `test_new_session_prompt_carries_project_process_notes` (steps, through the fake CLI's recorded prompt);
  - `test_plan_review_prompt_carries_digest`.
- [ ] FAIL, then implement, then PASS. Commit `feat(sp16): memory digest in every new worker session` with the memory and ops READMEs.

### Task 3: Recording: dedupe, `--process`, context footer

**Files:** `src/kengash_ai/memory.py`, `ops/workspace.py`, `cli.py`; tests `tests/test_memory.py`, `test_cli_workspace.py`.

**Produces:**
- `memory.normalized(line: str, *, decision: bool) -> str`, used by `add`.
- `memory.add_process(paths, text: str, *, project: str, by: str) -> AddResult`: file `PROCESS.md`, cap 100, refuses at the cap with the spec text, journals `memory.write` with `file: PROCESS.md`.
- `workspace.remember(..., process: bool)`; CLI `--process`, which refuses `--decision`, `--section` and `--rejected` with `UserError`.
- `prompts.RECORD_HINT` printed by `kengash context` as `# Record\n<hint>` (§3.5, at most 6 lines).

- [ ] Tests first:
  - `test_add_treats_case_and_punctuation_variants_as_recorded`;
  - `test_add_decision_dedupe_ignores_date_and_tag`;
  - `test_add_keeps_decisions_sharing_a_prefix`;
  - `test_add_process_appends_under_process_notes`;
  - `test_add_process_refuses_at_cap`;
  - `test_cli_memory_add_process_rejects_decision_flag`;
  - `test_context_ends_with_record_hint`.
- [ ] FAIL, then implement, then PASS. Commit `feat(sp16): near-duplicate memory, --process, record hint` with READMEs.

### Task 4: Plans record lasting decisions on approval

**Files:** `src/kengash_ai/ops/plans.py`, `memory.py` (`parse_decision(line) -> tuple[str, str, str]`), `cli.py` (approve output); tests `tests/test_ops_plans.py`, `test_cli_plans.py`, `test_memory.py`.

**Produces:** `PlanResult.decisions: int`. Approval records each `- ` line of `Lasting decisions` through `memory.add(decision=True, project=slug, by=by)`. A missing why becomes `plan <id>`. The CLI adds `DECISIONS.md +N lines` when N > 0.

- [ ] Tests first:
  - `test_parse_decision_splits_why_and_rejected`;
  - `test_approve_records_lasting_decisions`;
  - `test_approve_without_section_records_nothing`;
  - `test_cli_approve_prints_decisions_count`.
- [ ] FAIL, then implement, then PASS. Commit with READMEs.

### Task 5: Worker decisions land with the merge

**Files:** `src/kengash_ai/ops/steps.py` (`_finish`), `ops/prompts.py` (review blocks, `decision_lines`), `ops/merging.py`; tests `tests/test_ops_steps.py`, `test_ops_prompts.py`, `test_ops_merging.py`.

**Produces:**
- `prompts.decision_lines(existing: str, proposed: Sequence[Decision]) -> str`: ≤ 3 per reply, ≤ 6 total, deduplicated through `memory.normalized`.
- `_finish` writes `doc.sections["Decisions"]`.
- Review prompts (new and resumed) add a `("Decisions", ...)` block after Handoff.
- `merging.merge_ticket`, after the ff and save, records each line with `memory.add(decision=True, ...)`; the result gains `Merged.decisions: int`.

- [ ] Tests first:
  - `test_work_reply_decisions_go_to_ticket_section`;
  - `test_decisions_capped_per_reply_and_ticket`;
  - `test_review_prompt_shows_decisions`;
  - `test_merge_records_ticket_decisions`;
  - `test_parked_ticket_decisions_never_recorded`.
- [ ] FAIL, then implement, then PASS. Commit with READMEs.

### Task 6: Editing phase and path holders

**Files:** `src/kengash_ai/workflow.py`, `ops/lifecycle.py`; tests `tests/test_workflow.py`, `test_lifecycle.py`.

**Produces:**
- `workflow.edit_phase(settings: Settings, workflow: str, step: str | None, *, hitl: bool) -> bool`: true when the workflow has an edit-kind step at or before `step`'s index, false for an unknown step or no edit step.
- `lifecycle.holds_paths(resolved: Settings, ticket: Ticket) -> bool` (spec §3.7).

- [ ] Tests first:
  - `test_edit_phase_starts_at_first_edit_step`;
  - `test_edit_phase_false_without_edit_step`;
  - `test_holds_paths_planning_does_not_hold`;
  - `test_holds_paths_gates_release_but_awaiting_merge_holds`;
  - `test_holds_paths_waiting_paths_does_not_hold`.
- [ ] FAIL, then implement, then PASS. Commit with READMEs.

### Task 7: Scheduling: planning ignores paths, critical path first

**Files:** `src/kengash_ai/scheduler.py`, `ops/queue.py`, `ops/controls.py` (`_claim`); tests `tests/test_scheduler.py`, `test_ops_queue.py`, `test_ops_controls.py`.

**Produces:**
- `Candidate.editing: bool = True` and `Candidate.weight: int = 0`. Candidates with `editing=False` skip the overlap check and are not added to `taken`. `_in_turns` sorts by `(-weight, RANK, created, id)`.
- `scheduler.chain_weights(depends: Mapping[str, Sequence[str]]) -> dict[str, int]`: the longest chain of dependents, memoised; a cycle counts as 0.
- `queue.compute` builds Busy from `holds_paths` and weights from not-done tickets.
- `_claim` checks overlap only when the start step is in the editing phase, and only against holders.

- [ ] Tests first:
  - `test_planning_candidates_ignore_overlap`;
  - `test_editing_candidate_still_held_by_holder`;
  - `test_chain_weights_longest_dependent_chain`;
  - `test_critical_path_before_importance`;
  - `test_next_starts_overlapping_tickets_that_plan` (queue on a store);
  - `test_gate_ticket_does_not_hold_paths`;
  - `test_run_claims_planning_ticket_despite_overlap`.
- [ ] FAIL, then implement, then PASS. Commit with READMEs (scheduler, ops).

### Task 8: Jobs wait for paths

**Files:** `src/kengash_ai/ops/steps.py` (`_finish`, `_begin`, `run_job`), `ops/views.py` (`WAITING`, label `waiting paths`, the note from `waiting_on`), `ui/static` (status label if listed); tests `tests/test_ops_steps.py`, `test_ops_views.py`.

**Produces:**
- When `_finish` routes from a non-editing step into an editing-phase step, the status becomes `in_process/waiting_paths`.
- `_begin`, at `waiting_paths`, checks other holders' overlap under the lock. On a clash it saves `state.waiting_on = id` and journals `ticket.moved` with reason `touches overlap <id>` once per new id, then returns `_WaitPaths`. Otherwise it sets the step status and clears `waiting_on`.
- `run_job` sleeps `PATH_POLL_S` and beats on `_WaitPaths`.

- [ ] Tests first:
  - `test_job_waits_for_overlapping_holder_then_runs` (monkeypatch `PATH_POLL_S`, release the holder from another thread or by patching `holds`);
  - `test_job_enters_editing_without_wait_when_free`;
  - `test_waiting_journals_once_per_holder`;
  - `test_park_while_waiting_paths`;
  - `test_views_show_waiting_paths`.
- [ ] FAIL, then implement, then PASS. Commit with READMEs (ops, ui if touched).

### Task 9: Fresh base before the first edit

**Files:** `src/kengash_ai/gitops.py`, `ops/steps.py`; tests `tests/test_gitops.py`, `test_ops_steps.py`.

**Produces:** `gitops.catch_up(worktree: Path, base: str) -> bool`: an ff-only merge of `base` when `rev-list --count base..HEAD == 0` and the worktree is clean; returns whether HEAD moved. Called in `_step` before an edit-kind step's call, under the repo lock.

- [ ] Tests first:
  - `test_catch_up_fast_forwards_branch_without_commits`;
  - `test_catch_up_leaves_branch_with_commits`;
  - `test_catch_up_skips_dirty_worktree`;
  - `test_implement_starts_from_newest_base` (steps).
- [ ] FAIL, then implement, then PASS. Commit with READMEs.

### Task 10: Planner files narrow touches

**Files:** `src/kengash_ai/ops/steps.py` (`_finish`), `ops/prompts.py` (`narrowed(files) -> list[str] | None`); tests `tests/test_ops_prompts.py`, `test_ops_steps.py`.

**Produces:** In `_finish`, when the output is a `PlanOutput`, the step is not in the editing phase, and `narrowed(output.files)` is not None, it sets `ticket.touches` and appends `touches narrowed to N files` to the Log line.

- [ ] Tests first:
  - `test_narrowed_normalises_and_dedupes`;
  - `test_narrowed_rejects_absolute_dotdot_empty_and_over_40`;
  - `test_plan_reply_files_narrow_touches`;
  - `test_plan_reply_without_files_keeps_touches`.
- [ ] FAIL, then implement, then PASS. Commit with READMEs.

### Task 11: Merge queue recheck and auto-merge reasons

**Files:** `src/kengash_ai/ops/merging.py`, `ops/checks.py` (reuse), `cli.py` (merge output); tests `tests/test_ops_merging.py`, `test_cli_controls.py`.

**Produces:** `merge_ticket` holds `merge-<slug>.lock` throughout. After rebasing it notes `moved = head_before != head_after`. Checks run when `moved and checks.configured(resolved, ticket)` (commands set and an enabled check step). A fail goes through `_send_back(..., findings, check_output)`, which generalises the conflict path, journals `checks.end` with step `merge`, and raises `UserError("<id>: checks failed after rebase onto <base>; sent back to implement")`. A failed ff because main moved raises `UserError("<base> moved; run kengash merge <id> again")`. `merge_if_clean` journals the dirty or off-base reason as `ticket.awaiting_merge`.

- [ ] Tests first:
  - `test_merge_reruns_checks_when_base_moved`;
  - `test_merge_skips_checks_when_rebase_moved_nothing`;
  - `test_merge_check_failure_sends_back_and_keeps_main`;
  - `test_merges_of_one_project_serialize` (lock held: second merge waits);
  - `test_auto_merge_dirty_tree_journals_reason`.
- [ ] FAIL, then implement, then PASS. Commit with READMEs.

### Task 12: Skills

**Files:**
- role skills `src/kengash_ai/roles/plan/SKILL.md` (`files`, decisions), `roles/implement/SKILL.md` (decisions), `roles/review-code/SKILL.md` (Decisions check);
- conductor skills `skills/memory/SKILL.md` (criteria, `--process`), `skills/grill/SKILL.md` and `skills/plan/SKILL.md` (`## Lasting decisions`), `skills/ticket/SKILL.md` (width rules), `skills/loop/references/events.md` (record gate answers);
- tests `tests/test_ops_skills.py`, `test_cli_skills.py`.

- [ ] Tests first: assertions on the key phrases (`files`, `Lasting decisions`, `--process`, `depends_on` rule), plus the existing cap tests.
- [ ] FAIL, then edit, then PASS. Run the haiku wording micro-test on the ticket width rule and the memory criteria. Commit with READMEs (roles).

### Task 13: Contract docs

**Files:**
- `docs/superpowers/specs/2026-10-22-kengash-design.md` (§4.5, §5, §7, §9, settings default);
- `docs/superpowers/specs/2026-10-22-sp3-*` §7;
- `docs/conventions/memory-files.md`, `docs/architecture.md` (SP16 row), `AGENTS.md` status;
- the SP16 spec status line.

- [ ] `make docs` and `make check` green. Commit `docs(sp16): contract for shared memory and parallel tickets`.

### Task 14: Release 0.6.0 prep

**Files:** `pyproject.toml`, plugin manifests, `CHANGELOG.md` `[0.6.0]` (SP15 + SP16), README upgrade notes (`merge.mode` now `auto`; `kengash settings set merge.mode ask` to keep the old behaviour), `uv.lock`.

- [ ] `make check`, `make dist`, `make audit` green. Commit `chore(release): 0.6.0`.
