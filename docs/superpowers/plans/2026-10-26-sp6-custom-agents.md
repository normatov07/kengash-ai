# SP6 Custom Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Users add their own agents (role + step of kind read, edit or review) from SETTINGS.md, `harness agent new` or the Agents screen, and tickets run them like built-in steps; plus four canvas parity fixes.

**Architecture:** A `steps` section in Settings describes custom steps; `Settings.role_of`/`kind_of` replace every direct `STEP_ROLES` lookup, so engine, prompts, views and claims treat built-in and custom steps alike. `ops.agent_config` computes the key changes and writes them in one validated `settings.set_values` save plus a starter role skill; CLI and UI call only it.

**Tech Stack:** Python 3.12, Pydantic 2, Typer, FastAPI, ruamel (via `store.yamledit`), vanilla JS modules, pytest, node for JS unit checks.

**Spec:** `docs/superpowers/specs/2026-10-26-sp6-custom-agents-design.md`

## Global Constraints

- A change to `src/super_harness/<module>` updates `docs/modules/<module>/README.md` in the same commit (`make docs` enforces it).
- Only `harness` writes store files; every write goes through `ops` and is journaled (`settings.changed`, `by`) and committed.
- Built-in step names: `plan`, `review_plan`, `implement`, `review_code`, `security`, `run_tests`, `docs`, `approve`. Custom step names match `[a-z][a-z0-9_]{1,30}`; role names match `[a-z][a-z0-9-]{1,30}`; `does` ≤ 200 characters, one line.
- Kinds: `read` (read-only, work output, like `plan`), `edit` (edit_worktree, harness commits, like `implement`), `review` (read-only, review output, diff stat, on_fail allowed, stall streaks, like `review_code`). Internally `run_tests` is kind `check` (review output, no streaks) and `approve` has no kind; neither is offered for custom steps.
- Built-in behaviour must not change: every existing test passes unmodified except where a test indexes `STEP_ROLES` for a step list.
- UI copy follows the canvas: button "New agent"; kind cards "Reviewer", "Worker", "Advisor".

## Review Focus

1. Removing an agent while a ticket sits at its step: refused, naming the ticket (Task 4 test).
2. Names that collide: a built-in step or role, an existing custom one, `plan-reviewer` vs `plan_reviewer`: refused before anything is written (Task 1, Task 4 tests).
3. A `does` text with `:`, `#`, quotes or braces round-trips through SETTINGS.md unchanged (Task 4 test).
4. Project scope: adding an agent to one project leaves the defaults and every other project's file untouched (Task 4 test).
5. A custom review step that keeps failing hits the loop cap and asks for approval like `review_code` does (Task 2 test).

---

### Task 1: Custom steps in the Settings model

**Files:**
- Modify: `src/super_harness/model/settings.py`, `src/super_harness/model/__init__.py`
- Test: `tests/test_model_settings.py`
- Docs: `docs/modules/model/README.md`, `docs/conventions/memory-files.md` (SETTINGS keys)

**Interfaces:**
- Produces: `StepKind = Literal["read", "edit", "review"]`; `Kind = Literal["read", "edit", "review", "check"]`; `BUILTIN_KINDS: dict[str, Kind | None]` (`plan: read, review_plan: review, implement: edit, review_code: review, security: review, run_tests: check, docs: edit, approve: None`); `class CustomStep(_Section): role: str; kind: StepKind; does: str`; `Settings.steps: dict[str, CustomStep]`; `Settings.role_of(step: str) -> str | None` (None for `approve` and unknown names); `Settings.kind_of(step: str) -> Kind | None`; `Settings.step_names() -> list[str]` (built-ins in `STEP_ROLES` order, then custom in file order); `ROLE_NAME`, `STEP_NAME` compiled patterns.

- [ ] **Step 1: Failing tests** in `tests/test_model_settings.py`:
  - `test_a_custom_step_validates_and_resolves`: settings with `agents.perf-reviewer` and `steps.perf_review: {role: perf-reviewer, kind: review, does: "Check hot paths."}` in `workflows.critical` after `review_code` with `on_fail: {perf_review: implement}` → `role_of("perf_review") == "perf-reviewer"`, `kind_of("perf_review") == "review"`, `kind_of("run_tests") == "check"`, `role_of("approve") is None`, `step_names()[-1] == "perf_review"`.
  - `test_custom_step_problems` parametrized, each `pytest.raises(ValidationError, match=...)`: built-in name `steps.security` → "built-in"; bad name `steps.Perf` → "step name"; unknown role → "no agent"; `does` with a newline or 201 chars → "one line"; a workflow step that is neither built-in nor custom → "unknown steps"; `on_fail` from a custom `edit` step → "only review steps".
- [ ] **Step 2: Run** `uv run pytest tests/test_model_settings.py -q` → new tests FAIL.
- [ ] **Step 3: Implement** the interfaces above. Move the unknown-step check from `Workflow` to a `Settings` model validator next to `_steps_have_agents` (which now uses `role_of`). Keep `STEP_ROLES` exported for the built-in table.
- [ ] **Step 4: Run** `uv run pytest tests/test_model_settings.py tests/test_settings.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(model): custom steps in settings`.

### Task 2: Engine and prompts run custom steps

**Files:**
- Modify: `src/super_harness/workflow.py`, `src/super_harness/ops/prompts.py`, `src/super_harness/ops/steps.py`, `src/super_harness/ops/controls.py`, `src/super_harness/ops/queue.py`, `src/super_harness/ops/changes.py`, `src/super_harness/ops/reviews.py` (if it uses the step tables)
- Test: `tests/test_workflow.py` (or the existing workflow test file), `tests/test_ops_prompts.py`, `tests/test_ops_steps.py`
- Docs: `docs/modules/workflow/README.md`, `docs/modules/ops/README.md`

**Interfaces:**
- Consumes: Task 1's `role_of`, `kind_of`.
- Produces: `prompts.instruction(settings: Settings, step: str) -> str` (built-ins: today's `INSTRUCTIONS`; custom: `does` plus the kind's suffix — read: "Do not edit files.", edit: "Do not commit; harness commits.", review: "Read the changes with read-only git; fail only for real problems."); `prompts.output_kind(kind: Kind | None) -> OutputKind`; `prompts.profile(kind: Kind | None) -> Profile`; `new_prompt(..., instruction: str, ...)` and `resumed_prompt(..., instruction: str, review: bool, ...)` take the instruction and whether the step reviews instead of looking up by name.

- [ ] **Step 1: Failing tests:**
  - workflow: `test_a_custom_review_step_routes_like_review_code` — custom `perf_review` in `simple` after `review_code`, `on_fail: {perf_review: implement}`: `after(fail)` → `Run("implement", loop+1)`, streaks recorded under `perf_review`; at `loop == loop_max` → `Halt(NEEDS_APPROVAL, ..., "loop_cap")`; an agent `on: false` skips the step; `blocking: true` and off → `Halt(FAILED, "role perf-reviewer is off and blocking")`.
  - prompts: `test_custom_step_prompts_follow_their_kind` — `instruction()` for each kind ends with its suffix; `output_kind("check") == "review"`, `profile("edit") == "edit_worktree"`, `profile("review") == "read_only"`.
  - steps (fake CLIs, `write_settings` adding the custom agent and step to `simple` after `implement`): `test_a_custom_edit_step_is_committed` (fake claude edits `notes.md`; the branch log has `hrn(7b55e0c1): loop 1 tidy:`); `test_a_custom_review_step_sends_the_ticket_back` (fails → step `implement`, loop 2, Findings written); `test_a_custom_read_step_hands_notes_on` (Handoff set, no commit).
- [ ] **Step 2: Run** those tests → FAIL.
- [ ] **Step 3: Implement:** replace `STEP_ROLES[...]`/`.get` with `resolved.role_of(step)`, `REVIEWS` membership with `kind_of(step) == "review"`, `EDIT_STEPS`/`REVIEW_STEPS` membership with the kind, and `INSTRUCTIONS.get(step)` with `prompts.instruction(resolved, step)` at every call site listed in Files.
- [ ] **Step 4: Run** `uv run pytest -q` → all PASS (built-in behaviour unchanged).
- [ ] **Step 5: Commit** `feat(engine): run custom steps by kind`.

### Task 3: Views show custom steps

**Files:**
- Modify: `src/super_harness/ops/views.py`
- Test: `tests/test_ops_views.py`
- Docs: `docs/modules/ops/README.md`

**Interfaces:**
- Produces: `WorkflowsView.library` = `resolved.step_names()`, `.roles` = `{step: role_of(step)}`, new `.kinds: dict[str, str | None]`, `.does: dict[str, str]`; `Role.custom: bool` (role not among `STEP_ROLES` values), `Role.step: str | None` (its custom step); board columns: built-in order, then each custom step used by a workflow of the scope (title = step name with `_` → space, capitalised), before `approve` and `done`; `_place`, `_footer`, ticket chain and "who wrote this" use `role_of`.

- [ ] **Step 1: Failing tests:** `test_custom_steps_reach_the_workflow_view` (library ends with `perf_review`, `kinds["perf_review"] == "review"`, `roles["perf_review"] == "perf-reviewer"`); `test_the_roster_marks_custom_agents` (`custom` and `step` set, `used_in == ["critical"]`); `test_the_board_has_a_column_for_a_custom_step` (a ticket at `perf_review` shows in column `perf_review` titled "Perf review", placed before `done`).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `uv run pytest tests/test_ops_views.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(views): custom steps on the board, roster and workflow`.

### Task 4: `ops.agent_config` and `harness agent`

**Files:**
- Create: `src/super_harness/ops/agent_config.py`, `src/super_harness/roles/_starter/{read,edit,review}.md` (starter skill templates, package data)
- Modify: `src/super_harness/cli.py`, `pyproject.toml` (import-linter contract if modules are listed)
- Test: `tests/test_ops_agent_config.py`, `tests/test_cli_agents.py`
- Docs: `docs/modules/ops/README.md`, `docs/modules/cli/README.md`, `README.md` command list

**Interfaces:**
- Consumes: Task 1 model, `settings.set_values`, `settings.load`, `records.record`, `records.scope`, `skills.role_file`, `skills.lint` (whatever `harness skills lint` calls).
- Produces:
  - `@dataclass class AgentChange: project: str | None; role: str; step: str; keys: list[str]; skill_file: str` (`""` when an existing skill was kept or none removed).
  - `new_agent(role: str, *, kind: StepKind, does: str, cli: str = "claude", step: str | None = None, workflows: Sequence[str] = (), after: str | None = None, send_back: str | None = None, project: str | None, by: str) -> AgentChange` — step defaults to `role.replace("-", "_")`, skill name = role; inserts the step into each named workflow after `after` (default: before `approve` when present, else last); a review step gets `on_fail[step] = send_back` (default `implement` when that workflow has it, else no edge); one `set_values` save with `agents.<role>`, `steps.<step>`, `workflows.<name>` whole; then the starter skill at `<scope>/roles/<role>/SKILL.md` unless `skills.role_file` finds one; journals `settings.changed` and commits `harness: agent new <role>` under `settings.lock`.
  - `remove_agent(role: str, *, project: str | None, by: str) -> AgentChange` — refuses built-in roles ("switch it off instead"), roles not set in this scope's file, and a role whose step an `in_process` ticket of the scope (any project for defaults) sits at ("ticket <id> is at step <step>; move it first"); removes `agents.<role>`, its `steps.*`, those steps from every workflow and every `on_fail` edge naming them.
  - CLI: `agent_app` with `harness agent new ROLE --kind --does [--cli] [--step] [--workflow ...] [--after] [--send-back] [--project] [--by] [--json]` and `harness agent remove ROLE [--project] [--by] [--json]`; plain output one line: `added perf-reviewer: step perf_review in critical; skill roles/perf-reviewer/SKILL.md` / `removed perf-reviewer`.

- [ ] **Step 1: Failing tests** (`registered_repo`, `store_paths`, `journal_events`, `run_git` fixtures):
  - `test_new_agent_writes_one_valid_save_and_a_starter_skill`: keys `["agents.perf-reviewer", "steps.perf_review", "workflows.critical"]`; resolved critical steps `[plan, review_plan, implement, review_code, perf_review, security]` with `after="review_code"`; `on_fail["perf_review"] == "implement"`; the skill file exists, starts with `---\nname: perf-reviewer`, and `harness skills lint` passes on it; journal `settings.changed` by `cli`; store log has `harness: agent new perf-reviewer`.
  - `test_new_agent_refuses_without_writing` parametrized: role `security-reviewer`, role `plan_reviewer` (bad pattern), step `security`, unknown workflow `huge`, `after` not in the workflow, `send_back` on a `read` step → `UserError`; SETTINGS.md bytes unchanged and no skill dir created.
  - `test_does_round_trips_yaml_specials`: `does='Flag "N+1" queries: {hot: paths} # not a comment'` → `settings.load(...).steps["perf_review"].does` equal.
  - `test_a_project_agent_touches_only_that_project`: defaults file and `web-dashboard` (register a second repo via the existing helper) unchanged.
  - `test_remove_agent_cleans_workflows_and_edges` and `test_remove_refuses_built_ins_and_busy_steps` (a ticket `in_process/perf_review` at step `perf_review` → message names it).
  - CLI: `test_cli_agent_new_and_remove` (`CliRunner`, exit 0, the two plain lines, `--json` has `keys`).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `uv run pytest tests/test_ops_agent_config.py tests/test_cli_agents.py -q && uv run lint-imports` → PASS.
- [ ] **Step 5: Commit** `feat(ops): harness agent new and remove`.

### Task 5: UI — New agent, remove, status-flow add, library kinds

**Files:**
- Modify: `src/super_harness/ui/app.py`, `src/super_harness/ui/static/views/agents.js`, `.../views/settings.js`, `.../views/workflow.js`, `.../views/board.js` (titles from the server already), `src/super_harness/ui/static/app.css`
- Test: `tests/test_ops_ui_server.py`, `tests/test_ui_static.py`
- Docs: `docs/modules/ui/README.md`, SP5 spec §4 Agents and Settings rows

**Interfaces:**
- Consumes: Task 3 view fields, Task 4 `new_agent`/`remove_agent`.
- Produces: `POST /api/agents` body `NewAgent{project: str = "", role, kind, does, cli = "claude", step: str | None, workflows: list[str] = [], after: str | None, send_back: str | None}` → `views.AgentsView` (detect=False); `POST /api/agents/{role}/remove` body `{project: str = ""}` → same. Route `#/agents/new` opens the sheet.

- [ ] **Step 1: Failing tests:** server — `test_new_agent_endpoint_saves_and_needs_the_header` (200 with `X-Harness`, roster has the role with `custom: true`; 403 without the header; 400 with the `UserError` text for a built-in name); `test_remove_agent_endpoint`. Static — `test_agents_screen_offers_new_agent` (agents.js contains `New agent`, `Reviewer`, `Worker`, `Advisor`, posts `/api/agents`); `test_settings_status_flow_links_to_new_agent` (`#/agents/new` in settings.js).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** the endpoints (UserError → 400 already mapped by the app's handler) and the screens: accent "New agent" button in the Agents top bar; a sheet (reuse the ticket sheet's dimmed-overlay styles) with role, what it does, kind cards, CLI·model select from the provider cards, workflow checkboxes, "after" select, "send back to" select for Reviewer; "Remove agent" in a custom row's editor; Settings status flow "+ add" chip → `#/agents/new`; Workflow library and nodes use `kinds` to pick the icon (review → eye, edit → code, read → doc) and label custom outs by kind.
- [ ] **Step 4: Run** `uv run pytest tests/test_ops_ui_server.py tests/test_ui_static.py -q` → PASS; then in Chrome on the demo store create `perf-reviewer`, see it on Agents, Workflow and the board, remove it.
- [ ] **Step 5: Commit** `feat(ui): new agent sheet and custom steps`.

### Task 6: Canvas parity follow-ups

**Files:**
- Modify: `src/super_harness/ui/static/app.css`, `.../views/board.js`, `.../views/workflow.js`, `.../views/agents.js`
- Test: `tests/test_ui_static.py`
- Docs: `docs/modules/ui/README.md`

- [ ] **Step 1: Failing tests:** `test_board_titles_fit_seven_columns` (CSS: `.col-more` takes no space until hover or focus, `.col-head h2` letter-spacing ≤ 0.06em under `--col-min`); `test_queue_footer_stays_on_one_line` (`.col-open` has `white-space: nowrap`); `test_done_node_is_numbered` (workflow.js renders `${n} · Done`); `test_routing_names_the_loop_cap` (agents.js routing row includes `loops` when `loop_max` differs from simple's).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS; capture Board, Workflow, Agents at 1440 px beside the canvas with `tools/capture.mjs` and check no title is cut.
- [ ] **Step 5: Commit** `fix(ui): board titles, done node and routing match the canvas`.

### Task 7: Gemini note, docs and close-out

**Files:**
- Modify: `src/super_harness/adapters/__init__.py` (message), `docs/architecture.md`, `docs/superpowers/specs/2026-10-22-super-harness-design.md` (§4.6 `steps`, §13 roadmap row 6), `AGENTS.md` status line, `README.md`, the SP6 spec §7 boxes
- Test: `tests/test_adapters_core.py`

- [ ] **Step 1: Failing test** `test_gemini_points_to_antigravity`: `NeedsSetup` message contains "Antigravity" and "antigravity".
- [ ] **Step 2–4:** implement, `make check DOCS_BASE=main` green.
- [ ] **Step 5: Commit** `docs: SP6 complete`; push the branch; request review of the whole branch against this plan's Review Focus.
