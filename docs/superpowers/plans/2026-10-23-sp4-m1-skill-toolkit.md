# SP4 M1: Skill Toolkit and Role Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The seven role skills reach worker prompts from the package, the defaults or the project; `harness skills lint` and `harness skills install` work; the wheel carries the skills; plugin manifests validate; `doctor` reports a foreign `harness` on `PATH`.

**Architecture:** Skills are data: `src/super_harness/roles/<role>/SKILL.md` (package data) and `skills/<name>/SKILL.md` at the repo root (force-included in the wheel). `model.skills` parses frontmatter; `ops.skills` lints, installs and looks role skills up; `store.seed` copies role skills into `defaults/roles/`; `cli` hands its command tree to the lint.

**Tech Stack:** Python 3.12, pydantic 2, Typer/click, ruamel-yaml (`store.yamlio`), hatchling, pytest.

**Spec:** `docs/superpowers/specs/2026-10-23-sp4-skills-design.md` (decisions 2–10, §4, §6), system spec §8.

## Global Constraints

- A change to `src/super_harness/<module>` updates `docs/modules/<module>/README.md` in the same commit; new units `roles` (data) get a README under `docs/modules/roles/`.
- `ops` never imports `cli`; `store` imports only `model`.
- Skill caps: 80 lines, 400 words (`skill.max_lines`, `skill.max_words`); descriptions start with "Use when" and stay within 500 characters.
- No test runs a real provider; the plugin-validate test is `live`-marked.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A user's edited `defaults/roles/<role>/SKILL.md` survives `harness init` and `doctor --fix` (Task 2).
2. `harness skills install` run twice changes nothing the second time; a hand-edited installed skill is never overwritten without `--yes` (Task 4).
3. A skill mentioning `harness plan reveiw` (typo) fails lint; `harness --version` and `harness wait --timeout 540` pass (Task 3).
4. `--cli-name hrn` rewrites `harness plan new` but not the word "harness" in prose such as "the harness store" (Task 4).
5. `harness` on `PATH` missing entirely (running through `uv run`) is not a doctor warning (Task 5).

---

### Task 1: Commit the plan and the agy facts

- [ ] `make docs`; commit spec §2 decision 4 and §5 edits with this plan: `docs: SP4 M1 plan; agy skill folders`.

### Task 2: Role skills, lookup and seeding

**Files:** Create `src/super_harness/roles/{plan,review-plan,implement,review-code,review-security,run-tests,sync-docs}/SKILL.md`, `src/super_harness/model/skills.py`, `src/super_harness/ops/skills.py`, `docs/modules/roles/README.md`. Modify `src/super_harness/model/__init__.py`, `src/super_harness/ops/prompts.py` (`role_skill`), `src/super_harness/store/seed.py`. Test `tests/test_ops_skills.py`, `tests/test_store_basics.py` (or the seed test file), `tests/test_ops_prompts.py`.

**Interfaces:**
- `model.SkillMeta` (pydantic, extra allowed): `name: str`, `description: str`, `disable_model_invocation: bool = False` (alias `disable-model-invocation`), `metadata: dict[str, str] = {}`.
- `model.split_skill(text: str) -> tuple[dict[str, Any], str]`: frontmatter mapping and body; raises `UserError` without a `---` frontmatter block.
- `ops.skills.ROLES = ("plan", "review-plan", "implement", "review-code", "review-security", "run-tests", "sync-docs")`; `ops.skills.roles_dir() -> Path` (package `roles/`); `ops.skills.role_text(paths: StorePaths, slug: str, skill: str) -> str | None`: the body of `projects/<slug>/roles/<skill>/SKILL.md`, else `defaults/roles/…`, else the package's.
- `prompts.role_skill(paths, slug, skill)` returns `skills.role_text(...)`.
- `store.seed.ensure_store` copies every package role folder missing from `defaults/roles/`.

- [ ] **Step 1: Failing tests**: `test_role_text_prefers_project_then_defaults_then_package` (bodies only, no frontmatter), `test_role_text_is_none_for_an_unknown_skill`, `test_init_seeds_role_skills_and_keeps_edits` (an edited defaults role survives a second `ensure_store`), `test_every_role_has_a_skill` (each `ROLES` folder exists and `SkillMeta.name` equals it), `test_new_sessions_get_the_packaged_role_skill` (`_request` for a planner step carries the package `plan` body in `skill`).
- [ ] **Step 2: Run** — FAIL (no `ops.skills`).
- [ ] **Step 3: Implement**; write the seven role skills (frontmatter `name`, `description` "Use when …"; each a short checklist for its step, within the caps; `implement` and `sync-docs` say harness commits; reviewers say what earns a fail and to give file and line).
- [ ] **Step 4: Run** the tests and `tests/test_ops_steps.py` — PASS.
- [ ] **Step 5: Commit** `feat: packaged role skills, looked up per project and seeded into defaults`.

### Task 3: `harness skills lint`

**Files:** Modify `src/super_harness/ops/skills.py`, `src/super_harness/cli.py`, `Makefile` (`lint` runs `uv run harness skills lint`). Create `skills/README.md` (what the folder holds, for browsers of the repo). Test `tests/test_ops_skills.py`, `tests/test_cli_skills.py`.

**Interfaces:**
- `@dataclass ops.skills.Problem(path: str, message: str)`.
- `ops.skills.lint(targets: Sequence[Path], *, commands: Collection[str], caps: SkillCaps) -> list[Problem]`: each target is a `SKILL.md`, a skill folder, or a folder of skill folders; a skill whose folder sits in a `roles` folder gets the role rules, others the installed rules (spec decision 7). Messages: `name <n> does not match its folder <f>`, `name must be lowercase words joined by single hyphens, at most 64 characters`, `description must start with "Use when"`, `description has N characters; the cap is 500`, `N lines; the cap is C`, `N words; the cap is C`, `step 0 must run harness --version`, `references/<x> is missing`, `references/ must not hold folders`, `unknown command: harness <words>`.
- `ops.skills.mentions(body: str) -> list[list[str]]`: the words after `harness` in inline code spans and in fenced lines starting with `harness ` (or `$ harness `), up to the first word starting with `-`, `<`, `{` or a quote.
- `ops.skills.packaged() -> Path`: the installed skills folder (package `skills/`, else the checkout's `skills/`).
- CLI `harness skills lint [PATH…]`: default targets `packaged()` and `roles_dir()`; the command tree is every top-level command name plus `<group> <sub>` for each group command, from `typer.main.get_command(app)`.

- [ ] **Step 1: Failing tests**: one `test_lint_*` per message above on tmp skill folders; `test_mentions_reads_code_spans_and_fenced_commands` (`harness plan review <id>` → `["plan", "review"]`, `harness --version` → `[]`); `test_cli_lint_is_clean_on_the_repo` (exit 0, no output) and `test_cli_lint_names_an_unknown_command` (a tmp skill with `harness plan reveiw` → exit 1, `…: unknown command: harness plan reveiw`).
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS; `make lint` runs the lint.
- [ ] **Step 5: Commit** `feat: harness skills lint`.

### Task 4: `harness skills install`

**Files:** Modify `src/super_harness/ops/skills.py`, `src/super_harness/cli.py`, `pyproject.toml` (`[tool.hatch.build.targets.wheel.force-include] "skills" = "super_harness/skills"`). Test `tests/test_ops_skills.py`, `tests/test_cli_skills.py`.

**Interfaces:**
- `AGENT_DIRS = {"claude": ".claude/skills", "codex": ".agents/skills", "antigravity": ".agents/skills"}`; `GLOBAL_DIRS = {"claude": ".claude/skills", "codex": ".agents/skills", "antigravity": ".gemini/config/skills"}`; `agy` is accepted for `antigravity`.
- `@dataclass Installed(agent: str, name: str, state: Literal["installed", "updated", "unchanged", "differs"], folder: Path)`; `@dataclass InstallResult(entries: list[Installed], diffs: dict[str, str])` with property `needs_yes`.
- `ops.skills.install(agents: Sequence[str], *, root: Path, home: bool, cli_name: str = "harness", yes: bool = False, source: Path | None = None) -> InstallResult`: `root` is the repo root (`records.repo_root(path)`) or the home folder; each target folder once (codex and antigravity share `.agents/skills` in a repo); each skill folder rendered (`rename_cli` on `.md` files), compared file by file, written to a temp sibling and swapped in; `differs` without `yes` writes nothing and records a unified diff.
- `ops.skills.rename_cli(text: str, name: str) -> str`: replaces `harness` only where it starts a command (inside backticks or at the start of a fenced line, followed by a space and a word).
- CLI `harness skills install --agent A,B [--global] [--path DIR] [--cli-name N] [--yes] [--json]`: lines per §4; diffs printed after them; exit 5 when `needs_yes`; an unknown agent → exit 2 style `UserError`.

- [ ] **Step 1: Failing tests** (source = a tmp folder with two skills): `test_install_writes_each_agents_folder_once`, `test_install_twice_is_unchanged`, `test_a_hand_edited_skill_needs_yes_and_shows_a_diff`, `test_cli_name_rewrites_commands_not_prose`, `test_global_install_uses_each_agents_home_folder` (`home=True` with `root=tmp`), `test_cli_install_exits_5_until_yes`, `test_the_wheel_carries_skills_and_roles` (`uv build --wheel -o tmp`; the zip lists `super_harness/skills/README.md` and `super_harness/roles/plan/SKILL.md`).
- [ ] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat: harness skills install`.

### Task 5: Doctor reports a foreign `harness`

**Files:** Modify `src/super_harness/ops/projects.py` (or `providers.py`); Test `tests/test_ops_projects.py`.

**Interfaces:** `ops.providers.cli_clash() -> str | None`: when `shutil.which("harness")` exists and its `--version` output does not start with `super-harness `, `the first harness on PATH (<path>) is not super-harness; run hrn instead, and install skills with --cli-name hrn`; None when it is ours or absent. `doctor` adds it as a warning.

- [ ] **Step 1: Failing tests**: `test_doctor_warns_about_a_foreign_harness` (a tmp `harness` script printing `harness 2.1.0` first on PATH), `test_no_harness_on_path_is_fine` (PATH without one).
- [ ] **Steps 2–4**: run FAIL, implement, run PASS. **Step 5: Commit** `feat(ops): doctor reports a foreign harness on PATH`.

### Task 6: Plugin manifests

**Files:** Create `.claude-plugin/plugin.json` (`name: super-harness`, `description`, `version` = package version, `author: {name: normatov07}`, `repository`, `license`), `.claude-plugin/marketplace.json` (`name: super-harness`, `owner: {name: normatov07}`, one plugin with `source: "./"`). Test `tests/test_plugin.py` (`test_plugin_version_matches_the_package`), `tests/live/test_live_plugin.py` (`claude plugin validate .` and `agy plugin validate .` exit 0; skipped when the binary is missing).

- [ ] Write the tests, run (FAIL), write the manifests, run (PASS), run the live test, commit `feat: Claude plugin manifest and marketplace`.

### Task 7: Docs and review

- [ ] Module READMEs (`model`, `ops`, `store`, `cli`, new `roles`), `docs/architecture.md` (`roles` row built; SP4 M1), `docs/conventions/skills.md` (role skill format, install paths), `make check` green, commit `docs: SP4 M1 built`; review the M1 diff against the spec, fix Critical/Important test first, ledger minors.
