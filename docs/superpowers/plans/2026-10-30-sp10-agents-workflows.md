# SP10 Namespaced Skills, Agents and Workflows, UI Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every kengash skill under one `kengash` prefix in every agent CLI; built-in agents locked in what they do; the user's own agents and every workflow fully editable from the UI and the CLI; a UI with real controls that works from 360 px up.

**Architecture:** Skills keep short canonical folders; `kengash skills install` turns them into a `kengash` plugin (Claude Code skills-dir, Antigravity `agy plugin install`) or `kengash-<name>` copies (Codex, and agy's fallback). Agent and workflow changes are new `ops` entry points (`agent_config`, a new `ops.workflows`) that compute key changes and write them in one validated `settings.set_values` save, called by both the CLI and the UI. The UI gains a controls module and rewrites the Agents and Workflow screens on it; the engine is untouched apart from routing a new ticket through `routing`.

**Tech Stack:** Python 3.12+, Pydantic, Typer, FastAPI, vanilla JS modules, pytest, headless Chrome over CDP.

**Spec:** `docs/superpowers/specs/2026-10-30-sp10-agents-workflows-design.md`

## Global Constraints

- Skill names: `plan`, `grill`, `ticket`, `loop`, `ui`, `memory`; plugin `kengash`; marketplace `kengash-ai`. Written `/kengash:<name>`; Codex copies `kengash-<name>`, called `$kengash-<name>`.
- Built-in role → skill, fixed: planner plan, plan-reviewer review-plan, implementer implement, code-reviewer review-code, security-reviewer review-security, test-runner run-tests, doc-writer sync-docs.
- Exact messages: `agents.<role>.skill is fixed at <skill>; set it back, or copy the agent (kengash agent copy <role> <new>) to change what it does`; `<role> is a built-in agent; its <field> is fixed; copy it to change what it does`; `on_fail edges must send back to an earlier step: <a>-><b>`; `workflow name must match [a-z][a-z0-9_-]{0,30}`; `workflow <name> is used by open tickets: <ids>; finish or move them first`; `workflow <name> is routed from <importance>; route it elsewhere first`; `project <slug> sets workflow <name>; change it there first`; `old kengash skill names installed in <dir>; run: kengash skills install --agent <agent>`.
- Only kengash writes store files; every settings change is one locked, validated, comment-preserving `settings.set_values` save that journals `settings.changed` and commits (`records.record`).
- A change under `src/kengash_ai/<module>` updates `docs/modules/<module>/README.md` in the same commit; files under `docs/` stay ≤ 150 lines (specs and plans exempt).
- UI: every value through the `html` tagged template (escaped); every POST sends `X-Harness`; no `alert`/`confirm`/`prompt`; native form elements under custom styling.
- Never `claude --bare`, never read OAuth tokens, no API-key variables in workers (AGENTS.md hard rule 6).

## Review Focus

1. Own instructions whose text starts with `---` and a YAML-looking block are kept as body, not parsed as frontmatter (Task 8 test `test_instructions_that_look_like_frontmatter_stay_body`).
2. Editing a custom agent defined in the defaults while a project is in scope writes only that project's keys and `projects/<slug>/roles/<role>/` (Task 8 test `test_editing_a_defaults_agent_from_a_project_overrides_there`).
3. Renaming or removing a defaults workflow that a project overrides or routes to is refused, naming the project (Task 9 test `test_defaults_workflow_used_by_a_project_is_kept`).
4. A model typed through "Other…" that is empty or holds whitespace is refused (`model must be one word: <cli>`) (Task 5 test `test_models_are_one_word`).
5. Changing a custom agent's kind away from `review` while a project workflow sends back from its step is refused, naming the project, and writes nothing (Task 8 test `test_kind_change_refused_while_a_project_sends_back_from_it`).

---

## Milestone 1: Skill namespace

### Task 1: Spike the Antigravity plugin route

**Files:** none committed except a note in spec §7.

- [ ] **Step 1:** In a scratch folder build `kengash/` with the repo's `.antigravity-plugin/plugin.json` (name `kengash`) and `skills/loop/SKILL.md`; run `agy plugin validate <dir> --json`, then `agy plugin install <dir>`, `agy plugin list --json`, and `agy --help | grep -i plugin` (a per-session flag like `--plugin-dir`?). Run `agy -p "/kengash:loop" --output-format json` with the skill body replaced by "reply OK" to see the namespaced command resolve. Then `agy plugin uninstall kengash`.
- [ ] **Step 2:** Record in spec §7: which manifest path agy reads, whether a local folder installs, whether it is copied or linked, whether a session-only flag exists. If the local install fails, Task 3's agy route is the copy fallback only.
- [ ] **Step 3: Commit** `docs: SP10 agy plugin spike result`.

### Task 2: Short skill names and the `kengash` plugin manifests

**Files:** `git mv` `skills/to-plan`→`plan`, `to-plan-with-grill`→`grill`, `to-ticket`→`ticket`, `to-loop`→`loop`, `open-ui`→`ui`, `kengash-memory`→`memory`; `evals/<old>`→`evals/<new>`; Modify every SKILL.md (`name`, descriptions, cross-references), `skills/README.md`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.antigravity-plugin/plugin.json`, UI strings (`views/overview.js`, `board.js`, `app.js`, `settings.js`: every `/to-…` and `/open-ui`), `README.md`, system spec §8.1/§8.4; Test `tests/test_plugin.py`, `tests/test_ops_skills.py`, `tests/test_ui_static.py`.

- [ ] **Step 1: Failing tests.** `test_plugin_is_named_kengash` (both manifests `name == "kengash"`, marketplace `plugins[0].name == "kengash"`, marketplace `name == "kengash-ai"`); `test_installed_skills_are_the_six_short_names` (`{p.name for p in packaged().iterdir() if (p / "SKILL.md").is_file()} == {"plan","grill","ticket","loop","ui","memory"}`); `test_no_old_command_spelling_left` (no `/to-plan`, `/to-ticket`, `/to-loop`, `/open-ui`, `/to-plan-with-grill` in `skills/`, `src/kengash_ai/ui/static/`, `README.md`).
- [ ] **Step 2: Run** `uv run pytest tests/test_plugin.py tests/test_ops_skills.py tests/test_ui_static.py` → the three fail.
- [ ] **Step 3: Rename and rewrite.** Descriptions read "Use when the user runs /kengash:<name> …"; `memory` keeps its model-invoked description. Eval YAML `skill:` fields follow; turns become `{kg}loop`, `{kg}plan …`, `{kg}grill …`, `{kg}ticket {plan}`, `{kg}ui` (Task 4 fills `{kg}`).
- [ ] **Step 4: Run** the tests → pass; `uv run kengash skills lint` → clean.
- [ ] **Step 5: Commit** `feat(skills)!: kengash plugin with short skill names`.

### Task 3: `kengash skills install` per agent

**Files:** Modify `src/kengash_ai/ops/skills.py`, `src/kengash_ai/cli.py` (`skills_install` output only); Test `tests/test_ops_skills.py`, `tests/test_cli_skills.py`; Docs `docs/modules/ops/README.md`, `docs/modules/cli/README.md`.

**Interfaces:**
- Produces `PLUGIN = "kengash"`; `plugin_manifest() -> dict[str, str]` (name, version from `kengash_ai.__version__`, description, homepage, license); `install(agents, *, root, home=False, cli_name=CLI, yes=False, source=None, store: Path | None = None, run: Callable[[list[str]], int] = _run) -> InstallResult` (same result type; `Installed.name` is `kengash (plugin)` for a plugin route).
- Layout: claude → `root/.claude/skills/kengash/.claude-plugin/plugin.json` + `skills/<name>/…`; codex → `root/.agents/skills/kengash-<name>/` (home: `~/.agents/skills/`); antigravity → plugin built at `<store>/runtime/plugin/kengash/` then `run(["agy", "plugin", "install", <dir>])`; on a nonzero exit or no `agy` on PATH, copies as codex but under `GLOBAL_DIRS["antigravity"]` with `--global`, entries state `installed` and a `fallback` note.
- Copies rewrite `name: <x>` → `name: kengash-<x>` and `/kengash:<x>` → `$kengash-<x>` for codex, `/kengash-<x>` for the agy fallback, on top of `rename_cli`.

- [ ] **Step 1: Failing tests.** `test_claude_gets_a_skills_dir_plugin` (manifest name `kengash`, `skills/loop/SKILL.md` has `name: loop`); `test_codex_gets_prefixed_copies` (`.agents/skills/kengash-loop/SKILL.md` has `name: kengash-loop` and `$kengash-loop`, no `/kengash:`); `test_agy_installs_the_plugin_and_falls_back` (fake `run` returning 0 → one `kengash (plugin)` entry, argv `["agy","plugin","install", …/runtime/plugin/kengash]`; returning 1 → prefixed copies); `test_install_removes_old_names_of_ours_only` (an old `.claude/skills/to-loop` with `metadata: {source: kengash-ai}` removed, a foreign `.claude/skills/to-loop` without the marker kept); `test_install_twice_is_unchanged` for each route; update `test_global_install_uses_each_agents_home_folder`.
- [ ] **Step 2: Run** `uv run pytest tests/test_ops_skills.py tests/test_cli_skills.py` → new tests fail.
- [ ] **Step 3: Implement** in `ops/skills.py`: `_obsolete(folder, keep)` is reused on `.claude/skills` and `.agents/skills` with the old and current names to keep; `_render(skill, cli_name, spelling)` gains the name/command rewrite; plugin folders go through `_swap`. `_run` uses `subprocess.run(..., capture_output=True, timeout=120)`.
- [ ] **Step 4: Run** the tests → pass; `make lint type` silent.
- [ ] **Step 5: Commit** `feat(skills): install as the kengash plugin, or kengash- copies for Codex`.

### Task 4: Doctor, evals and a live check

**Files:** Modify `src/kengash_ai/ops/skills.py` (`old_installs`), `src/kengash_ai/ops/projects.py` (`doctor`), `src/kengash_ai/ops/evals.py`; Test `tests/test_ops_projects.py`, `tests/test_ops_evals.py`; Docs `docs/modules/ops/README.md`, `evals/README.md`.

**Interfaces:** Produces `skills.old_installs(roots: Sequence[Path]) -> list[tuple[Path, str]]` (folder, agent) scanning `.claude/skills`, `.agents/skills`, `.gemini/config/skills` under each root for our-marked folders with the old names; `evals.agent_values` adds `"kg"` (`/kengash:` for claude and antigravity-plugin, `$kengash-` for codex, `/kengash-` for the agy fallback); `conductor_argv(..., plugin_dir: Path | None = None)` adds `--plugin-dir <dir>` for claude.

- [ ] **Step 1: Failing tests.** `test_doctor_warns_about_old_skill_names` (registered repo with an old `.claude/skills/to-loop` of ours → warning with the exact message, agent `claude`); `test_agent_values_spell_each_cli` (the four `kg` values); `test_claude_conductor_loads_the_plugin_dir`.
- [ ] **Step 2: Run** → fail. **Step 3: Implement** (`doctor` scans every registered repo and `Path.home()`; `run_scenario` passes `repo/.claude/skills/kengash` for claude; agy evals use the route Task 1 found, else the fallback copies). **Step 4: Run** → pass.
- [ ] **Step 5: Live:** `kengash skills install --agent claude --global` then a new interactive `claude` lists `/kengash:loop` etc. and `claude plugin list` shows `kengash@skills-dir` (by hand); `make evals` → every scenario passes on claude and agy. Record results in the spec's M1 boxes.
- [ ] **Step 6: Commit** `feat: doctor and evals speak the kengash skill names`.

## Milestone 2: Agents and workflows

### Task 5: Settings rules

**Files:** Modify `src/kengash_ai/model/settings.py`, `src/kengash_ai/store/defaults/SETTINGS.md` (a commented `routing:` block); Test `tests/test_model_settings.py`; Docs `docs/modules/model/README.md`, system spec §4.6.

**Interfaces:** Produces `BUILTIN_SKILLS: dict[str, str]` (Global Constraints map); `IMPORTANCES = ("simple", "standard", "critical")`; `WORKFLOW_NAME = re.compile(r"[a-z][a-z0-9_-]{0,30}")`; `Settings.routing: dict[str, str]`; `Settings.workflow_for(importance: str) -> str` (routing entry, else the importance).

- [ ] **Step 1: Failing tests.** `test_builtin_skills_are_fixed` (`agents.planner.skill: other` → exact message); `test_routing_defaults_and_validation` (no key → `workflow_for("critical") == "critical"`; `routing.critical: hotfix` with `workflows.hotfix` → `"hotfix"`; unknown target → `routing.critical: no workflow hotfix`; unknown importance key → error); `test_on_fail_sends_back_only` (`on_fail: {plan: review_code}` in `[plan, implement, review_code]` → exact message); `test_workflow_names` (`Hot Fix` refused with the exact message); `test_a_step_appears_once` (`steps: [plan, plan]` → `workflows.<name>: step plan appears twice`); `test_models_are_one_word` (`claude/`, `claude/opus 4` → `model must be one word: <cli>`; `claude/opus[1m]` accepted).
- [ ] **Step 2: Run** `uv run pytest tests/test_model_settings.py` → fail. **Step 3: Implement** as `@model_validator(mode="after")` methods beside `_custom_steps`; the model rule in `_known`. **Step 4: Run** → pass, and the whole suite (`make test`) to catch fixtures with forward edges.
- [ ] **Step 5: Commit** `feat(model): fixed built-in skills, importance routing, send-back only`.

### Task 6: Built-in role skills come from the package

**Files:** Modify `src/kengash_ai/ops/skills.py` (`role_file`, `role_text`), `src/kengash_ai/store/seed.py` (drop `_seed_roles`), `src/kengash_ai/ops/projects.py` (`doctor`); Test `tests/test_ops_skills.py`, `tests/test_ops_projects.py`; Docs ops and store READMEs, system spec §8.2.

**Interfaces:** Produces `skills.ignored_copies(paths: StorePaths) -> list[Path]` (store `roles/<builtin skill>/` folders, defaults and every project).

- [ ] **Step 1: Failing tests.** Replace `test_role_text_prefers_project_then_defaults_then_package` with `test_builtin_skills_ignore_store_copies` (a `defaults/roles/review-code/SKILL.md` and a project copy → `role_file` returns the package path) and `test_custom_skills_prefer_project_then_defaults`; replace `test_init_seeds_role_skills_and_keeps_edits` with `test_init_seeds_no_role_skills`; `test_doctor_lists_ignored_builtin_copies` (warning `ignored <path>: built-in skills are fixed; copy the agent to change it`; the file still exists).
- [ ] **Step 2: Run** → fail. **Step 3: Implement.** **Step 4: Run** → pass. **Step 5: Commit** `feat: built-in role skills always load from the package`.

### Task 7: Tickets follow routing; the engine runs any order

**Files:** Modify `src/kengash_ai/ops/tickets.py:91-117`; Test `tests/test_ops_tickets.py`, `tests/test_workflow.py`, `tests/test_lifecycle.py`; Docs ops README.

- [ ] **Step 1: Failing tests.** `test_new_tickets_take_the_routed_workflow` (`routing.critical: hotfix` → an added critical ticket has `workflow == "hotfix"` and `loop_max == loop_max.critical`); `test_custom_agent_runs_anywhere` (parametrized positions first, middle, last, before `approve`: `steps_for` order and `before`/`after` routing match the list); lifecycle `test_a_custom_step_first_runs_first` with the fake CLIs (the custom step's session runs before `plan`).
- [ ] **Step 2: Run** → the routing test fails. **Step 3: Implement:** `workflow=resolved.workflow_for(item.importance.value)` and the missing-workflow check uses it. **Step 4: Run** → pass. **Step 5: Commit** `feat(ops): new tickets take the importance's routed workflow`.

### Task 8: Edit, copy and describe agents

**Files:** Modify `src/kengash_ai/ops/agent_config.py`; Test `tests/test_ops_agent_config.py`; Docs ops README.

**Interfaces:**
- Produces `AgentPatch` (dataclass, all fields `None` = unchanged): `cli: str | None`, `fallback: list[str] | None`, `on: bool | None`, `blocking: bool | None`, `bypass_permissions: bool | None`, `kind: StepKind | None`, `does: str | None`, `skill: str | None`, `instructions: str | None`.
- `new_agent(...)` (SP6 signature) gains `fallback: Sequence[str] = ()`, `skill: str | None = None`, `instructions: str | None = None` (`skill` and `instructions` exclusive; neither → the kind's starter, as now).
- `edit_agent(role: str, patch: AgentPatch, *, project: str | None, by: str) -> AgentChange`; `copy_agent(source: str, new: str, *, project: str | None, by: str) -> AgentChange`.
- `AgentDetail` dataclass with exactly the spec §6 agent fields; `describe(paths: StorePaths, resolved: Settings, project: str | None, role: str) -> AgentDetail`; `UsedIn(workflow: str, position: int)`.
- `set_instructions(paths, project, role, text, caps: SkillCaps) -> Path` writes `<scope>/roles/<role>/SKILL.md` = generated frontmatter (spec §4.2) + `text`, refusing over the caps with `instructions have <n> lines; the cap is <cap>` (words likewise).

- [ ] **Step 1: Failing tests.** `test_edit_changes_only_given_fields`; `test_builtin_refuses_kind_does_skill_instructions` (each → the built-in message naming the field; `cli`, `fallback`, `on`, `blocking`, `bypass_permissions` saved); `test_own_instructions_are_written_and_capped`; `test_instructions_that_look_like_frontmatter_stay_body`; `test_use_a_skill_points_at_any_role_skill`; `test_kind_change_drops_review_edges` (keys show `workflows.critical` without the edge); `test_kind_change_refused_while_a_project_sends_back_from_it` (nothing written); `test_editing_a_defaults_agent_from_a_project_overrides_there`; `test_copy_builtin_makes_an_own_agent` (kind `review`, cli and fallback copied, instructions = the package `review-code` body); `test_copy_refuses_test_runner`; `test_describe_lists_where_used`.
- [ ] **Step 2: Run** → fail. **Step 3: Implement** reusing `_with_step` and the settings lock as `new_agent` does. **Step 4: Run** → pass. **Step 5: Commit** `feat(ops): edit, copy and describe agents; own instructions`.

### Task 9: Workflow management

**Files:** Create `src/kengash_ai/ops/workflows.py`; Test `tests/test_ops_workflows.py`; Docs ops README, `docs/architecture.md` ops row.

**Interfaces:** Produces `WorkflowChange(project: str | None, name: str, keys: list[str])`; `new_workflow(name, *, from_: str | None = None, project, by)`, `rename_workflow(old, new, *, project, by)`, `remove_workflow(name, *, project, by)`, `route(importance, workflow, *, project, by)`, `set_workflow(name, steps: list[str], on_fail: dict[str, str], *, project, by)`, each `-> WorkflowChange`.

- [ ] **Step 1: Failing tests.** `test_new_blank_and_copied` (blank → `steps: [implement]`); `test_names_are_checked`; `test_rename_moves_routing`; `test_in_use_by_tickets_is_kept` (an in-queue ticket on it → exact message with its id); `test_routed_workflow_is_kept`; `test_defaults_workflow_used_by_a_project_is_kept`; `test_route_and_set_validate` (`set_workflow` with an edge to a missing step → the settings error, nothing written).
- [ ] **Step 2: Run** → fail. **Step 3: Implement** like `agent_config` (lock, `settings.load`, one `set_values`, `records.record`). **Step 4: Run** → pass. **Step 5: Commit** `feat(ops): create, rename, remove, route and set workflows`.

### Task 10: CLI parity

**Files:** Modify `src/kengash_ai/cli.py`; Test `tests/test_cli_agents.py`, create `tests/test_cli_workflows.py`; Docs cli README, system spec CLI list.

- [ ] **Step 1: Failing tests.** `agent new … --fallback claude/sonnet,antigravity --instructions-file -` (stdin); `agent edit perf-reviewer --cli codex --off`; `agent edit planner --kind read` exits 1 with the built-in message; `agent copy code-reviewer strict-reviewer`; `agent show perf-reviewer --json` has `instructions` and `used_in`; `workflow new hotfix --from simple`, `workflow route critical hotfix`, `workflow rename hotfix quickfix` (routing follows), `workflow set quickfix --steps plan,implement,review_code --on-fail review_code=implement`, `workflow remove` refused while routed.
- [ ] **Step 2: Run** → fail. **Step 3: Implement** `agent edit|copy|show` and a `workflow` Typer group (help: "Workflows: create, route and edit the step lists."), each through one ops call, `-p` = the existing `Scope` alias, `--json` via `_emit`. **Step 4: Run** → pass; `uv run kengash skills lint` still clean. **Step 5: Commit** `feat(cli): agent edit, copy, show and the workflow commands`.

## Milestone 3: Controls and the Agents screen

### Task 11: Agents API

**Files:** Modify `src/kengash_ai/ops/views.py` (`AgentsView`, `agents_view`), `src/kengash_ai/adapters/base.py`, `adapters/claude.py`, `adapters/antigravity.py`, `src/kengash_ai/ui/app.py`; Test `tests/test_ops_views.py`, `tests/test_ui_app.py`, `tests/test_adapters_antigravity.py`; Docs ops, adapters, ui READMEs.

**Interfaces:** `Provider.models() -> list[str]` (claude `["fable","opus","sonnet","haiku"]`, codex and shell `[]`, antigravity: ids from `agy models`, the first tab field of each line after "Fetching…", `[]` on failure or timeout 20 s), fetched with detection and cached with it; `ProviderCard.models: list[str]`; `AgentsView.agents: list[AgentDetail]` (replaces `roster`), `AgentsView.skills: list[SkillRef(name, source)]`; `routing`/`loop_max` leave `AgentsView`. Routes: `POST /api/agents/{role}` body `{project, patch}` → `edit_agent`; `POST /api/agents/{role}/copy` body `{project, new}`; existing create gains `fallback`, `skill`, `instructions`; each returns the fresh `AgentsView`; a `KengashError` is a 400 with its message.

- [ ] **Step 1: Failing tests.** `test_agy_models_parse` (the 2026-10-30 output → six ids); `test_agents_view_details` (built-in `planner`: `builtin`, `instructions_own: False`, package text; a custom one: own text, `used_in` positions); `test_edit_copy_endpoints_need_the_header_and_refuse_cleanly` (no header → 403; built-in kind change → 400 with the message; nothing written).
- [ ] **Step 2–4:** run → fail, implement, run → pass. **Step 5: Commit** `feat(ui): agents API with details, models, edit and copy`.

### Task 12: Controls kit and the responsive shell

**Files:** Create `src/kengash_ai/ui/static/controls.js`; Modify `app.css`, `app.js` (nav menu), `index.html` if the nav markup lives there; Test `tests/test_ui_static.py`; Docs ui README.

**Interfaces** (`controls.js`, each returns an `html` template; `bind*` wires one root):
- `select({ id, name, value, options: [[value, label, disabled?]], label })`
- `modelPicker({ id, providers, value })` → CLI select, model select of that CLI's `models` plus `default` and `Other…`, a text field shown for `Other…`; `bindModelPicker(root, onChange)`; `modelValue(root) -> "provider[/model]"`
- `chipList({ id, items, options })` ordered chips with ✕ and an add-select; `bindChipList(root, onChange)` (drag and Alt+↑/↓ reorder)
- `segmented({ name, value, options: [[value, label, hint]] })` (radio group), `toggle({ id, checked, label })`
- `instructions({ id, value, caps, readonly })` textarea with live `n / cap lines · n / cap words`; `bindInstructions(root)`
- `agentPicker({ agents })` popover with search, groups Yours and Built-in, "+ New agent…"; `bindAgentPicker(root, onPick)`

- [ ] **Step 1: Failing tests.** `test_controls_module_is_served_and_parses` (joins `test_every_module_parses`); `test_no_text_input_offers_a_datalist` (no `list=` in any view); `test_breakpoints_exist` (`app.css` has `@media (max-width: 1280px)`, `900px`, `600px`); `test_nav_folds_into_a_menu` (a `[data-nav-toggle]` button with `aria-expanded`).
- [ ] **Step 2–4:** run → fail, implement, run → pass. Nav below 900 px: a menu button opens the existing links as a vertical sheet; Escape and outside click close it.
- [ ] **Step 5: Commit** `feat(ui): controls kit and a navigation that folds on small screens`.

### Task 13: Agents screen

**Files:** Rewrite `src/kengash_ai/ui/static/views/agents.js`; Modify `app.css`, `app.js` (route `#/agents/<role>`, `#/agents/new`); Test `tests/test_ui_static.py`; Docs `docs/modules/ui/README.md` (its parity checklist: Agents follows the SP10 spec, not the canvas).

- [ ] **Step 1:** Build spec §5.3 on Task 12's controls and Task 11's API: list (search; Yours, Built-in; icon by kind; CLI · model; on switch) beside the editor; header, Role, Model, Instructions, Behaviour, Used in, sticky footer; drafts per role in module state, one Save posting each drafted role's patch, then the provider limits panel below. Below 900 px list and editor stack with a back control.
- [ ] **Step 2: Static tests** `test_agents_screen_offers_new_agent` (kept), `test_builtin_editor_locks_role_and_instructions` (template contains `data-locked` on both sections for `builtin`).
- [ ] **Step 3: Browser check** on `scripts/demo_store.py` in headless Chrome: create, edit every field, copy, remove, switch agents with unsaved drafts and save both; captures at 390, 820, 1280, 1440 with `scrollWidth == clientWidth`; axe clean; no console or CSP error.
- [ ] **Step 4: Commit** `feat(ui): agents screen with a full editor`.

## Milestone 4: Workflow screen and polish

### Task 14: Workflows API

**Files:** Modify `src/kengash_ai/ops/views.py` (`WorkflowsView`), `src/kengash_ai/ui/app.py`; Test `tests/test_ops_views.py`, `tests/test_ui_app.py`.

**Interfaces:** `WorkflowsView.routing: dict[str, str]` (each importance → `workflow_for`), `WorkflowsView.picker: list[PickAgent(role, step, kind, builtin, on)]` (spec §6's "agents"; the existing `agents` field keeps role → CLI). Routes `POST /api/workflows` `{project, name, from}`, `POST /api/workflows/{name}/rename` `{project, new}`, `POST /api/workflows/{name}/remove` `{project}`, each through `ops.workflows` and returning the fresh `WorkflowsView`.

- [ ] **Steps:** failing tests `test_workflows_view_has_routing_and_picker`, `test_workflow_endpoints_refuse_in_use` → implement → pass → commit `feat(ui): workflows API for create, rename and remove`.

### Task 15: Workflow screen

**Files:** Modify `src/kengash_ai/ui/static/views/workflow.js`, `graph.js` (a `+` port per link with `data-insert-at`), `app.css`; Test `tests/test_ui_static.py`; Docs `docs/modules/ui/README.md` (parity checklist: Workflow follows the SP10 spec).

- [ ] **Step 1:** Spec §5.4: tabs with "+ New workflow" (dialog: name, blank or copy) and ⋯ (rename dialog, copy, delete via `armed` two-click, refusal shown inline); `+` on every link opens `agentPicker` and inserts at that index; pointer drag of a node and Alt+↑/↓ reorder; inspector: agent select (swap per spec §4.7), send-back select (earlier steps or "stop and ask me"), remove; Importance panel: per importance a workflow select and a max-loops number. One Save posts `workflows.<name>`, `routing.<imp>`, `loop_max.<imp>` via `/api/settings`. Below 900 px the inspector and panels go under the graph and "fit" is the default zoom.
- [ ] **Step 2: Static tests** `test_every_link_has_an_insert_port` (`layout()` output for 3 steps yields 4 `data-insert-at`), `test_send_back_targets_only_earlier_steps`.
- [ ] **Step 3: Browser check** on the demo store: new, copy, rename, delete and the in-use refusal; insert on each link; drag and keyboard reorder; swap; send-back; routing and loops save and reload; captures at the four widths; axe clean.
- [ ] **Step 4: Commit** `feat(ui): workflow editor with insert anywhere, reorder and routing`.

### Task 16: Input audit and the remaining screens

**Files:** Modify `views/settings.js` (`plan.reviewer` and `memory.compactor` → `modelPicker` with a "different provider" option for the reviewer; `merge.mode` → `segmented`; `grill.round_size` → `select` 1–4), `views/board.js`, `overview.js`, `memory.js`, `ticket.js`, `app.css`; Test `tests/test_ui_static.py`.

- [ ] **Step 1:** Replace each closed-choice input; board columns scroll inside the board with `scroll-snap-type: x mandatory` below 900 px; overview and memory grids collapse to one column below 600 px; the ticket sheet goes full screen below 600 px.
- [ ] **Step 2: Browser check** of all seven screens at 360, 390, 820, 1280 and 1440 px: no page-level sideways scroll, no overlapping text (read every capture), axe clean; the five canvas screens still match their boards at 1440 px (`canvas-parity-method`).
- [ ] **Step 3: Commit** `fix(ui): real controls everywhere; every screen from 360 px`.

### Task 17: Close-out

- [ ] Tick the spec's acceptance boxes with evidence; `docs/architecture.md` (modules, SP10 row); AGENTS.md status line (10 sub-projects; "UI design source": Agents and Workflow follow the SP10 spec); README (install and the `/kengash:` commands, no `npx skills add`); CHANGELOG (Breaking: skill names, built-in skills fixed and store copies ignored; Added; Fixed); system spec §4.6, §8.
- [ ] `make check` and `make dist` green; `make evals` green on claude and agy; whole-branch review against the spec; commit `docs: SP10 complete`.
