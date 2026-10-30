# SP9 Completion Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close what the 2026-10-27 audit found open against the original request: a project name-or-folder argument end to end, tags on board cards, and the kengash names SP8 missed in tooling and the live suite.

**Architecture:** `--project` values become slugs in one Typer option callback that calls `ops.workspace.project_slug`, so no use case, flag, ping or journal line ever sees a path. Skills only add `-p <project>` to commands that already take it. The board card gains a tag chip run; nothing changes for cards without tags.

**Tech Stack:** Python 3.12+, Typer, vanilla JS modules, pytest, headless Chrome over CDP.

**Spec:** `docs/superpowers/specs/2026-10-27-sp9-completion-audit-design.md`

## Global Constraints

- Exit 4 text, exactly: `not a kengash project: <folder>; run: kengash init <folder>` (`NeedsSetup`). Unknown name, exactly: `unknown project: <value>` (`UserError`, exit 1).
- A registered slug always wins over a folder of the same name.
- Skills stay within 80 lines and 400 words (`kengash skills lint`); every command they name exists.
- A module change updates its `docs/modules/<module>/README.md` in the same commit.

## Review Focus

1. `-p .` or `-p src/api` from inside a repo resolves to that repo's slug (Task 1 test).
2. Nested registered repos (`/code/mono` and `/code/mono/tools`): a folder in `tools` resolves to the inner one (Task 1 test).
3. `-p ~/code/x/` with `~` and a trailing slash resolves (Task 1 test).
4. A slug that is also a folder name in the current folder resolves to the slug (Task 1 test).
5. `-p` on a group-level command (`ticket list`, `agent new`) gets the same resolution (Task 1 test through `ticket list`).

---

### Task 1: `--project` takes a name or a folder

**Files:** Modify `src/kengash_ai/ops/workspace.py`, `src/kengash_ai/cli.py` (the `Project`, `Only`, `Here`, `Every`, `Scope` aliases); Test `tests/test_ops_workspace.py`, `tests/test_cli_queue.py`, `tests/test_cli_controls.py`; Docs `docs/modules/ops/README.md`, `docs/modules/cli/README.md`, system spec §6.

**Interfaces:** Produces `workspace.project_slug(value: str, cwd: Path, paths: StorePaths | None = None) -> str`; `cli._project(value: str | None) -> str | None` as `callback=` on all five aliases.

- [ ] **Step 1: Failing tests.** `test_project_slug_takes_a_name_or_a_folder` (slug; repo folder; a subfolder; `~`-expanded path with trailing slash via `monkeypatch.setenv("HOME", …)`; relative `.` from inside), `test_project_slug_prefers_the_deepest_repo` (outer repo with an inner registered repo), `test_project_slug_prefers_a_slug_over_a_folder` (folder named `payments-api` in cwd that is not the repo), `test_project_slug_refuses_unknown_names_and_strangers` (`nope` → `UserError` "unknown project: nope"; an unregistered existing folder → `NeedsSetup` with the exact init line). CLI: `test_next_takes_a_project_folder` (`next -p <repo>` equals `next -p payments-api`; `ticket list -p .` lists the ticket; an unregistered folder exits 4 naming `kengash init`), `test_pause_takes_a_project_folder` (`pause -p <repo>` → `runtime.pause_state(store_paths).covers("payments-api")`).
- [ ] **Step 2: Run** `uv run pytest tests/test_ops_workspace.py tests/test_cli_queue.py tests/test_cli_controls.py` → the new tests fail (`project_slug` missing; exit 1 on a folder).
- [ ] **Step 3: Implement.** `project_slug`: registry hit returns it; else `(cwd / Path(value).expanduser()).resolve()`; an existing directory picks the registered entry whose path equals it or is among its parents, longest path first; none → `NeedsSetup`; not a directory → `UserError`. `_project` returns `None` for `None`, else runs `project_slug(value, Path.cwd())` inside `_errors()`. Help text: "Project name or folder; …" keeping each alias's default clause.
- [ ] **Step 4: Run** the three test files → pass; `make lint type` → silent (import-linter: `cli` still imports only `ops`).
- [ ] **Step 5: Docs and commit** — ops and cli READMEs (Interface, Changes), system spec §6 sentence "`--project`/`-p` takes a project name or a folder inside a registered project (SP9)"; `feat(cli): --project takes a project name or folder`.

### Task 2: Skills pass the project on

**Files:** Modify `skills/to-loop/SKILL.md`, `skills/to-ticket/SKILL.md`, `skills/to-plan/SKILL.md`, `skills/to-plan-with-grill/SKILL.md`; Docs `skills/README.md` if it lists arguments, system spec §8.1 rows.

- [ ] **Step 1:** Each skill names its optional trailing argument in one line ("The user may name a project or its folder after the command; call it `<project>`") and adds `-p <project>` only where Spec decision 2 says: to-loop `next`, `wait`, `status`; to-ticket quick `plan new`; to-plan and to-plan-with-grill `context`, `plan new`. Each adds: exit 4 `not a kengash project` → ask the user whether to register it; only on yes `kengash init <folder>`, then retry.
- [ ] **Step 2: Run** `uv run kengash skills lint` → clean; `wc -w` each skill ≤ 400.
- [ ] **Step 3: Commit** `feat(skills): an optional project for planning, ticketing and the loop`.

### Task 3: Tags on board cards

**Files:** Modify `src/kengash_ai/ui/static/views/board.js` (`card`), `src/kengash_ai/ui/static/app.css`; Docs `docs/modules/ui/README.md`; `scripts/demo_store.py` gives two demo tickets tags.

- [ ] **Step 1:** `card()` appends, after status chips, `#tag` chips (class `cchip plain`) for the first three of `item.tags`, then `+N` when more; no element when `tags` is empty.
- [ ] **Step 2: Check** headless Chrome on a fresh demo store: the tagged cards show chips, an untagged card has no `#` chip, no console or CSP problem; `uv run pytest tests/test_ui_static.py tests/test_ui_app.py` → pass.
- [ ] **Step 3: Commit** `feat(ui): board cards show their tags`.

### Task 4: Kengash names in tooling and the live suite

**Files:** Modify `Makefile` (`lint`, `evals`), `scripts/demo_store.py` (home `<dir>/.kengash`, `KENGASH_HOME`, help and final line `kengash ui open`), `tests/live/test_live_smoke.py:181` (`--grep=Kengash-Ticket: <uuid>`).

- [ ] **Step 1:** Make the three edits.
- [ ] **Step 2: Run** `make check 2>&1 | grep -c "harness is now kengash"` → `0`; `uv run python scripts/demo_store.py <tmp>` prints `KENGASH_HOME=… uv run kengash ui open`; `uv run pytest -m live -k "end_to_end"` → claude and antigravity pass, codex skipped.
- [ ] **Step 3: Commit** `fix: kengash names in make targets, the demo store and the live smoke`.

### Task 5: Close-out

- [ ] Tick SP9 acceptance with evidence; `docs/architecture.md` SP9 row; `AGENTS.md` status line (9 sub-projects); CHANGELOG 0.2.0 Added/Fixed; `make check` and `make dist` green; whole-branch review; commit `docs: SP9 complete`.
