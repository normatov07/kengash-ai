# SP7 Production Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make super-harness fast on large stores, safe to package and publish, hardened, and documented for users and contributors.

**Architecture:** Content-keyed parse caches in `store` and `settings` remove the repeated YAML work; a header middleware hardens the UI; packaging, CI, release and community files follow PyPA and OpenSSF practice; small ops changes add log retention and a Windows guard.

**Tech Stack:** Python 3.12–3.14, ruamel.yaml (+ clib), FastAPI, hatchling, uv, GitHub Actions, pypa/gh-action-pypi-publish, Dependabot, axe-core.

**Spec:** `docs/superpowers/specs/2026-10-26-sp7-production-design.md`

## Global Constraints

- A change to `src/super_harness/<module>` updates `docs/modules/<module>/README.md` in the same commit.
- Caches return copies; a changed file is never served stale (content-keyed, not stat-keyed: tests rewrite files in place within one timestamp tick).
- No new runtime dependency except `ruamel.yaml.clib` on CPython. No PyYAML (YAML 1.1 reads `on` as a boolean).
- Actions pinned by full commit SHA with the tag in a comment; `permissions` least-privilege per workflow/job.
- Copy: Windows message "harness runs on Linux and macOS; on Windows use WSL".

## Review Focus

1. A ticket or SETTINGS.md rewritten in place with the same size shows the new content on the next view (Task 1 test).
2. A caller mutating a returned ticket or settings object does not change what the next caller gets (Task 1 test).
3. The CSP blocks nothing the screens need: every screen renders in Chrome with zero CSP console errors (Task 3 check).
4. Log pruning never removes a file newer than `keep_days`, nor anything at `keep_days: 0` (Task 4 test).
5. The sdist contains `skills/`, `src/super_harness/ui/static/fonts/` and no `.claude/` (Task 5 check).

---

### Task 1: Content-keyed parse caches and faster YAML

**Files:** Create `src/super_harness/store/memo.py`. Modify `store/yamlio.py`, `store/documents.py`, `settings.py`, `ops/views.py` (`overview` scans tickets once), `pyproject.toml` (`ruamel.yaml.clib>=0.2.12; platform_python_implementation == 'CPython'`), `uv.lock`. Tests: `tests/test_memo.py`, `tests/test_settings.py`. Docs: store, settings, ops READMEs. Script: `scripts/bench_views.py` (manual benchmark, not in CI).

**Interfaces:** `memo.Memo(maxsize: int)` with `get_or_make(key: Hashable, make: Callable[[], T]) -> T` (thread-safe LRU); `memo.digest(data: bytes) -> bytes` (blake2b-16). `documents.load_ticket/load_plan` cache `(kind, digest)` → parsed `Doc` and return `Doc(meta.model_copy(deep=True), dict(sections))`. `settings._parse` caches by text digest; `settings._resolve` caches `Settings` by the tuple of layer digests and returns `model_copy(deep=True)`. `yamlio.load_yaml` uses a thread-local `YAML(typ="safe", pure=False)`.

- [ ] **Step 1: Failing tests** — `test_memo_evicts_least_recently_used`; `test_a_ticket_rewritten_in_place_is_read_again` (save, `path.write_text` same-length edit of the title, `load_ticket` shows the new title); `test_loaded_documents_are_copies` (mutate `doc.meta.title` and `doc.sections`, reload unchanged); `test_settings_are_parsed_once_per_content` (monkeypatch `settings.load_yaml` counting calls: two `load` calls → package+defaults parsed once; edit defaults → parsed again; returned Settings mutation does not leak).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4:** `uv run pytest -q` → PASS; `scripts/bench_views.py <big store>` → every view < 1 s warm.
- [ ] **Step 5: Commit** `perf: content-keyed parse caches`.

### Task 2: SP6 deferred minors

**Files:** `ops/agent_config.py`, `ops/views.py`; tests `tests/test_ops_agent_config.py`, `tests/test_ops_views.py`.

- [ ] **Step 1: Failing tests** — `test_new_agent_reads_settings_under_the_lock` (monkeypatch `settings.load` to assert `settings.lock` file is held via `filelock` `is_locked` on a probe lock attempt with timeout 0 raising Timeout); `test_a_custom_column_sits_where_its_workflow_runs_it` (perf_review after review_code in critical → column order … review_code, perf_review, security …).
- [ ] **Steps 2–4**: implement (load inside the lock in `new_agent`/`remove_agent`; insert custom columns after the latest built-in step that precedes them in the first workflow using them); run → PASS.
- [ ] **Step 5: Commit** `fix: agent edits read under the lock; custom columns in workflow order`.

### Task 3: UI security headers and ruff security rules

**Files:** `ui/app.py`; `pyproject.toml` (`[tool.ruff.lint] select += "S"`, `ignore = ["S603", "S607"]` with comment, `per-file-ignores` tests `S101`, `S108`); `model/settings.py` (`_known(..., shell=)` → `allow_shell=`), `ops/steps.py` (assert → explicit `UserError`); tests `tests/test_ui_app.py`.

- [ ] **Step 1: Failing test** `test_every_response_carries_the_security_headers` for `/`, `/static/app.js`, `/api/meta`, a 401 and a 403: the seven headers of spec §3.4 exactly.
- [ ] **Steps 2–4**: implement the headers in the `guard` middleware (also on its early returns); `uv run ruff check` clean with `S`; run tests → PASS; Chrome: all seven screens on the demo store with no CSP violation in the console.
- [ ] **Step 5: Commit** `feat(ui): security headers; ruff security rules`.

### Task 4: Log retention and the Windows guard

**Files:** `model/settings.py` (`Logs(keep_days: int = Field(30, ge=0))`, `Settings.logs`), `store/defaults/SETTINGS.md` (documented key), `ops/jobs.py` (`prune_logs(paths, keep_days, now=None) -> int` called at job start), `ops/projects.py` (doctor `--fix` prunes), `cli.py` (Windows guard in the app callback); tests `tests/test_ops_jobs.py`, `tests/test_cli.py`.

- [ ] **Step 1: Failing tests** — `test_old_logs_are_pruned_and_new_ones_kept` (files aged 31 and 29 days by `os.utime`; `keep_days=30` removes 1; `keep_days=0` removes none); `test_native_windows_stops_with_the_wsl_message` (monkeypatch `cli.sys.platform = "win32"`; `harness --version` → exit 4, message).
- [ ] **Steps 2–4**: implement; run → PASS.
- [ ] **Step 5: Commit** `feat: log retention; native Windows says to use WSL`.

### Task 5: Packaging, CI, release and dependency updates

**Files:** `.gitignore`; `pyproject.toml` (classifiers, keywords, `[project.urls]`, `[tool.hatch.build.targets.sdist] include = [...]`); create `scripts/check_dist.py` (`main(dist_dir) -> int`: wheel has `super_harness/ui/static/fonts/inter.woff2`, `super_harness/skills/to-loop/SKILL.md`, `super_harness/store/defaults/SETTINGS.md`; sdist has `skills/`, `src/`, `LICENSE`; neither has `.claude/`, `.superpowers/`, `.import_linter_cache/`, `.venv/`, `__pycache__/`, `full prompt of app.md`); `Makefile` `dist` target; `.github/workflows/ci.yml` (matrix 3.12/3.13/3.14, `concurrency`, `timeout-minutes`, jobs `package` and `audit`); create `.github/workflows/release.yml`, `.github/dependabot.yml`; tests `tests/test_check_dist.py`.

- [ ] **Step 1: Failing tests** for `check_dist` on synthetic wheel/sdist archives (missing font → problem; `.claude/x` → problem; good → 0).
- [ ] **Steps 2–4**: implement; `make dist` → passes on the real build; `actionlint` (via `uvx`/docker if available, else YAML parse) on the workflows.
- [ ] **Step 5: Commit** `build: clean artifacts, release workflow, CI matrix and audits`.

### Task 6: Accessibility pass

**Files:** UI static files as findings require; `tests/test_ui_static.py` for any rule worth pinning.

- [ ] Run axe-core (pinned npm tarball in the scratchpad) on the seven screens of the demo store at 1440 px; fix serious and critical violations; re-run to zero; commit `fix(ui): accessibility findings`.

### Task 7: Docs, community files, close-out

**Files:** `README.md`, create `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `.github/ISSUE_TEMPLATE/{bug_report.yml,feature_request.yml,config.yml}`, `.github/pull_request_template.md`, `docs/releasing.md`; `docs/architecture.md`, system spec §13 row 7, `AGENTS.md` status, SP7 spec §4 boxes.

- [ ] Write them; `make check` green; push the branch; final review against Review Focus; commit `docs: SP7 complete`.
