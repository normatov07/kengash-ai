# SP8 Kengash Naming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every name a user types or sees becomes kengash, while a 0.1.0 install upgrades untouched and the old names keep working through 0.2.x.

**Architecture:** Each old name is read in one place and written in one place; readers accept old and new, writers write new. A one-time, link-leaving store migration runs at every entry point before anything else.

**Tech Stack:** Python 3.12+, Typer, FastAPI, git, pytest.

**Spec:** `docs/superpowers/specs/2026-10-26-sp8-kengash-naming-design.md`

## Global Constraints

- Deprecation text, exactly: `harness is now kengash; the harness and hrn names stop working in 0.3.0` (stderr only).
- New forms: command `kengash`; `~/.kengash`; `KENGASH_HOME`, `KENGASH_AGENT`; link `.kengash`; subject `kg(<id>):`; trailers `Kengash-Ticket`, `Kengash-Model`; branch `kg/<id>`; worktree `kg-<id>`; header `X-Kengash`; cookie `kengash_token_{port}`; store commits `kengash: …`; `by: kengash`; skill `kengash-memory`; version `0.2.0`.
- Old forms still read: `HARNESS_HOME`, `HARNESS_AGENT`, `.harness` link and real folder, `Harness-*` trailers, `hrn(` subjects, stored `hrn/` branches, existing `hrn-<id>` worktrees, `source: super-harness` skills.
- A module change updates its `docs/modules/<module>/README.md` in the same commit.

## Review Focus

1. Migration with a running worker or an open UI: the old path still resolves through the link (Task 1 test asserts the link).
2. `~/.harness` already a symlink (someone linked it by hand) or a file: nothing moves (Task 1 test).
3. `--json` under an old name: stdout is pure JSON, the warning is on stderr (Task 3 test).
4. A ticket claimed under 0.1.0 (`hrn/<id>`, `hrn-<id>` worktree, `Harness-Ticket` commits) resumes, shows its changes and merges (Task 4 test).
5. A foreign skill folder named like an obsolete one is never deleted (Task 6 test).

---

### Task 1: Store home and the one-time migration
**Files:** `store/paths.py` (`ENV_HOME = "KENGASH_HOME"`, `LEGACY_ENV_HOME = "HARNESS_HOME"`, `kengash_home()` replaces `harness_home()`), create `store/migrate.py` (`legacy_home(home: Path | None = None) -> str | None`: returns a one-line note when it moved the store, else None), call it from `cli.main`, `worker.__main__.main`, `ui.__main__`; tests `tests/test_store_migrate.py`; docs store, cli, worker, ui.
- [ ] Failing tests: moves `~/.harness` → `~/.kengash` and leaves `~/.harness` a symlink to it, data intact, a project link pointing into the old path still resolves; idempotent second run; both real dirs → nothing moves; `~/.harness` a symlink or file → nothing moves; `KENGASH_HOME` or `HARNESS_HOME` set → nothing moves, and `kengash_home()` prefers `KENGASH_HOME` over `HARNESS_HOME` over `~/.kengash`.
- [ ] Implement; run; commit `feat(store): ~/.kengash with a one-time link-leaving migration`.

### Task 2: The `.kengash` project link
**Files:** `store/links.py` (`LINK = ".kengash"`, `LEGACY_LINK = ".harness"`), `ops/projects.py` (init/link/adopt/doctor/scan), `ops/views.py` link health; tests `tests/test_ops_projects.py`, `tests/test_links.py`.
- [ ] Failing tests: `init` writes `.kengash` + exclude line; `doctor` reports a legacy `.harness` link ("replace it: kengash doctor --fix"); `doctor --fix` leaves `.kengash` → store, no `.harness`, exclude line added; `adopt` and the nearby scan accept a real `.harness/` folder.
- [ ] Implement; run; commit `feat(store): .kengash project links; doctor replaces .harness`.

### Task 3: Commands, version, agent variable, clash check
**Files:** `pyproject.toml` scripts (`kengash = "kengash_ai.cli:app"`, `harness`/`hrn = "kengash_ai.cli:legacy"`), `cli.py` (`legacy()` prints the deprecation line to stderr then runs `app`; `By` envvar `["KENGASH_AGENT", "HARNESS_AGENT"]`; `name="kengash"`), `adapters/env.py` (sets `KENGASH_AGENT`), `ops/waiting.py`, `ops/reviews.py` (read both), `ops/providers.py` (`cli_clash` looks for `kengash`), `__init__.py` `0.2.0`, plugin manifests version; tests `tests/test_cli.py`, `tests/test_ops_providers.py`, `tests/test_plugin.py`.
- [ ] Failing tests: `legacy()` via `CliRunner` with `prog_name="harness"`: stderr has the line once, `--json` stdout parses; `kengash --version` → `kengash-ai 0.2.0`; `--by` falls back to `HARNESS_AGENT`; worker env has `KENGASH_AGENT`.
- [ ] Implement; run; commit `feat(cli): kengash command; harness and hrn deprecated`.

### Task 4: Git conventions
**Files:** `ops/steps.py` (subject `kg(`, `Kengash-*` trailers), `ops/controls.py` (`kg/<id>`), `store/paths.py` (`worktree()` prefers an existing `hrn-<id>`, else `kg-<id>`), `gitops.py` (`ticket_commits` greps both trailers), `ops/changes.py` (model from `Kengash-Model` or `Harness-Model`), `ops/merging.py`; role skills `review-code`, `review-security` (`kg(`); tests `tests/test_ops_steps.py`, `tests/test_gitops.py`, `tests/test_ops_changes.py`.
- [ ] Failing tests: a new step commit has the new subject and trailers; a claim makes `kg/<id>` and `kg-<id>`; a ticket with `hrn/` branch, `hrn-` worktree and `Harness-*` commits shows its changes and merges.
- [ ] Implement; run; commit `feat(engine): kg commit, branch and worktree names; old ones still read`.

### Task 5: UI and store wording
**Files:** `ui/app.py`, `ui/static/api.js`, every `records.record`/`commit_store` message and `by="harness"` in `ops`, `memory.py`; tests `tests/test_ui_app.py` and the store-log assertions.
- [ ] Failing test: POST without `X-Kengash` → 403, with it → 200; cookie `kengash_token_<port>`. Then the wording change with the existing tests updated to `kengash:`.
- [ ] Implement; run; commit `feat: kengash in the UI header, cookie, store commits and journal`.

### Task 6: Skills
**Files:** `skills/harness-memory` → `skills/kengash-memory`, every `skills/*/SKILL.md`, `skills/README.md`, `ops/skills.py` (`mentions` reads `kengash` commands, `rename_cli` from `kengash`, `cli_name="kengash"`, obsolete cleanup), `.claude-plugin`, `.antigravity-plugin`, `evals/**`, `ops/evals.py` (`KENGASH_HOME`, `kengash` binary); tests `tests/test_ops_skills.py`, `tests/test_ops_evals.py`, `tests/test_plugin.py`.
- [ ] Failing tests: installed set holds `kengash-memory`; an installed `harness-memory` with `source: super-harness` is removed and reported `removed`; one without our source stays; `rename_cli(text, "kgx")` rewrites `kengash` commands.
- [ ] Implement; `kengash skills lint`; run; commit `feat(skills): kengash commands; kengash-memory; obsolete skills of ours removed`.

### Task 7: Sweep, docs, release notes
**Files:** tests, README, AGENTS.md, CONTRIBUTING, SECURITY, docs/**, CHANGELOG (0.2.0), system spec note, SP8 spec boxes.
- [ ] `git grep` for each old form; change every one that names the CLI or store; keep the concept word; `make check`, `make dist`; Chrome smoke of the UI on a store migrated from a 0.1.0 layout; commit `docs: SP8 complete`; push.
