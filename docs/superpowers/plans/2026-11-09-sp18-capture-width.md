# SP18 Capture and Width Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** What the user settles reaches memory on its own; ticket graphs come out wide and path claims match the edits.

**Architecture:** A detached one-shot `harvest` job on the cheap model, fed by a spool, with a verbatim-quote guard. Pure graph functions in `scheduler.py`, surfaced by `ticket add --check`, `next` and `watch`.

**Tech Stack:** Python 3.12+, pydantic, typer, pytest with the `fake_clis` fixture.

**Spec:** `docs/superpowers/specs/2026-11-09-sp18-capture-width-design.md`

## Global Constraints

- Harvest never fails the command that triggered it; hooks always exit 0.
- A worker (`KENGASH_AGENT` set) or a folder outside a registered project is never harvested.
- Quote: at least 2 words, found in the user's words, ignoring case and spacing.
- Limits: 8 facts per entry, 16,000 characters, 3 attempts, 8 new chat words, `why` 18 words, `rejected` 12 words, digest decisions 4,000 characters.
- Each change to `src/kengash_ai/<module>` updates `docs/modules/<module>/README.md`.
- Nothing is committed until the user asks.

## Review Focus

- A transcript line cut off mid-write at hook time: the cursor stops at the last whole line, nothing is lost or read twice.
- The harvest's own `claude -p` session ending: it must not start another harvest.
- `settings.json` with invalid JSON or an existing hook: left intact, hook added once.
- A provider CLI that is missing: entry kept, attempts counted, the job ends instead of spinning.
- A `quote` copied with different spacing or case still matches; one not in the user's words (only in agent text) is dropped.

---

### Task 1: Memory lines

**Files:** Modify `src/kengash_ai/memory.py`, `src/kengash_ai/ops/steps.py:484`, `src/kengash_ai/cli.py`, `src/kengash_ai/ops/workspace.py`. Test `tests/test_sp18_memory.py`.

**Interfaces — Produces:**
- `memory.add(..., user: bool = False)`: decision lines become `- <date> [<tag>] (user) <text>`.
- `memory.key` ignores `(user) `.
- `memory.digest(paths, project, root=None, touches=())`.
- `memory.forget(paths, text, project, by) -> str` (the removed line).
- `memory.supersede(paths, line, by) -> bool`.
- `memory.decision_lines(paths, project) -> list[str]`, `memory.memory_lines(paths)` (public names of the private readers).

- [ ] Tests: `test_user_mark_ignored_by_duplicates`, `test_why_and_rejected_are_tightened`, `test_digest_puts_user_and_touched_lines_first_in_file_order`, `test_digest_drops_date_and_tag`, `test_forget_removes_one_line`, `test_forget_refuses_zero_or_several`, `test_supersede_moves_line_to_archive_and_keeps_pinned`.
- [ ] Run, expect fail. Implement. Run, expect pass.

### Task 2: Harvest job

**Files:** Create `src/kengash_ai/ops/harvest.py`. Modify `model/steps.py`, `model/runtime.py`, `model/settings.py`, `store/paths.py`, `store/runtime.py`, `store/defaults/SETTINGS.md`, `ops/jobs.py`, `ops/prompts.py`, `worker/__main__.py`, `tests/conftest.py`. Test `tests/test_sp18_harvest.py`.

**Interfaces — Produces:**
- `HarvestFact`, `HarvestOutput`, output kind `"harvest"`; `HarvestEntry(source, project, text, quotable, attempts)`.
- `harvest.submit(paths, source, project, text, quotable=None) -> bool` (never raises; False when skipped).
- `harvest.run_harvest() -> str`, `harvest.fail_harvest(reason)`.
- `prompts.harvest_prompt(text, decisions, memory) -> str`.

- [ ] Tests: `test_a_quoted_fact_is_recorded_with_user_mark`, `test_quote_ignores_case_and_spacing`, `test_unquoted_fact_is_dropped`, `test_one_word_quote_is_dropped`, `test_each_kind_reaches_its_file`, `test_replaces_moves_the_old_decision`, `test_at_most_eight_facts`, `test_missing_cli_keeps_entry_and_counts_attempt`, `test_third_failure_drops_entry`, `test_off_setting_skips`, `test_text_is_redacted_and_capped`.
- [ ] Run, expect fail. Implement. Run, expect pass.

### Task 3: Triggers and chat hook

**Files:** Modify `ops/plans.py`, `ops/tickets.py`, `ops/controls.py`, `ops/harvest.py`, `ops/skills.py`, `ops/workspace.py`, `cli.py`. Test `tests/test_sp18_triggers.py`.

**Interfaces — Consumes:** `harvest.submit`. **Produces:**
- `harvest.from_hook(payload: str) -> None`, `harvest.queue_plan(plan_id, project) -> str`.
- `harvest.read_chat(path, offset) -> tuple[ChatSlice, int]`.
- CLI `memory harvest [--hook|--plan ID]`, `memory forget TEXT`.
- `skills.install_hooks(settings_path, cli_name) -> str`.
- `Context.recent` lines in `kengash context`.

- [ ] Tests: `test_plan_approve_queues_prompt_decisions_assumptions`, `test_plan_reject_queues_reason`, `test_quick_plan_queues_at_ticket_add`, `test_approve_note_queues_answer`, `test_plan_save_needs_lasting_decisions`, `test_none_is_enough`, `test_hook_skips_workers`, `test_hook_skips_unregistered_folder`, `test_hook_reads_each_message_once`, `test_hook_stops_at_last_whole_line`, `test_hook_ignores_under_eight_words`, `test_agent_text_is_context_not_quotable`, `test_question_answers_are_quotable`, `test_hook_never_raises_on_bad_json`, `test_install_hooks_merges_once`, `test_install_hooks_leaves_bad_json`.
- [ ] Run, expect fail. Implement. Run, expect pass.

### Task 4: Graph shape

**Files:** Modify `scheduler.py`, `gitops.py`, `ops/tickets.py`, `model/documents.py`, `model/settings.py`, `cli.py`. Test `tests/test_sp18_graph.py`.

**Interfaces — Produces:**
- `scheduler.Shape(tickets, levels, widest, chokepoints)`, `scheduler.shape(depends) -> Shape`, `scheduler.behind(depends) -> dict[str, set[str]]`.
- `gitops.hot_files(repo, ref, *, commits=400, at_least=3) -> list[tuple[str, int]]`.
- `tickets.check_batch(plan_id, text, *, project) -> BatchCheck`; `Batch.shape`.
- `TicketInput.needs: dict[str, str]`.

- [ ] Tests: `test_shape_levels_and_widest`, `test_chokepoint_past_first_level`, `test_first_level_is_not_a_chokepoint`, `test_dependency_without_need_is_refused`, `test_needs_land_in_scope`, `test_check_creates_nothing_and_reports`, `test_hot_files_counts_tickets_not_commits`, `test_test_root_claim_no_longer_clashes`, `test_same_test_file_still_clashes`.
- [ ] Run, expect fail. Implement. Run, expect pass.

### Task 5: Claims follow edits, stuck tickets

**Files:** Modify `ops/steps.py`, `ops/queue.py`, `ops/watch.py`, `cli.py`. Test `tests/test_sp18_claims.py`.

**Interfaces — Produces:** `steps._claim_edits(job, resolved, ticket) -> tuple[int, str | None]`; `queue.Stuck(id, project, status, behind)`, `queue.stuck(docs, slug) -> list[Stuck]`, `Queue.stuck`, `Board.stuck`.

- [ ] Tests: `test_edit_outside_touches_joins_claim`, `test_shared_files_stay_unclaimed`, `test_whole_repo_claim_unchanged`, `test_new_clash_is_journaled`, `test_failed_ticket_holding_three_is_listed`, `test_two_behind_is_not_listed`, `test_next_prints_waiting_on`, `test_watch_prints_waiting_on`.
- [ ] Run, expect fail. Implement. Run, expect pass.

### Task 6: Skills, roles, docs

**Files:** `skills/{ticket,plan,grill,memory}/SKILL.md`, `skills/ticket/references/width.md`, `src/kengash_ai/roles/{review-plan,plan,implement}/SKILL.md`, `docs/conventions/memory-files.md`, `docs/architecture.md`, `docs/modules/*/README.md`, `AGENTS.md`, `CHANGELOG.md`.

- [ ] Update wording. `make check` green.
- [ ] Skill evals on the changed flows; live proof from spec §4.
