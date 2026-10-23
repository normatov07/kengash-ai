# SP5 M2: Inspect and Configure Screens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ticket detail, Workflow editor, Agents and providers, Project settings and the full Memory store screen work against the store, and every save to SETTINGS.md keeps its comments and untouched lines.

**Architecture:** `settings.set_values` splices changed entries into SETTINGS.md (ruamel round-trip only to locate lines); `ops.configure.save_settings` wraps it with the lock, the journal and the store commit. New read models in `ops.views` (`ticket`, `settings`, `workflows`, `providers`, `memory`) feed new `ui` endpoints; each screen is one ES module under `ui/static/views/`.

**Tech Stack:** as M1 (FastAPI, plain ES modules, Chrome checks through Claude in Chrome); ruamel.yaml round-trip mode.

**Spec:** `docs/superpowers/specs/2026-10-23-sp5-ui-design.md` (decisions 7, 8, 10, 12; §3 endpoints; §4 rows Ticket detail, Workflow editor, Agents, Settings, Memory); system spec §4.6, §10.

## Global Constraints

- As M1: `ui` imports only `ops` and `model`; canvas colours and type; every rendered string escaped; no network fetches; module docs change with modules; commits end with the Co-Authored-By line.
- Every action journals `by: "ui"`; every store write goes through `ops`.
- Destructive actions (force move to done, Adopt, Reset overrides) need a second click on the same button within 4 s.
- Canvas elements that no setting or `ops` call backs go to the spec §4 "Left out" column, not into code.

## Review Focus

1. A save leaves every line it did not change byte-identical: comments, blank lines, the column alignment of sibling flow maps (`agents:` rows) (Task 2).
2. An invalid save (`loop_max.simple: 0`, an `on_fail` edge to a step not in the workflow, an unknown key) leaves the file as it was and the screen shows the reason (Tasks 2, 3).
3. Two tabs saving different keys: both changes survive, because a save applies only its keys to the file on disk under the lock (Task 2).
4. A ticket with no journal events, no plan file, no branch and no sessions renders every section empty, not an error (Task 6).
5. Slow provider detection (each CLI's sign-in check) never delays the other screens (Task 4).

---

### Task 1: M1 review follow-ups
**Files:** Modify `ui/app.py`, `journal.py`, `ops/views.py`; Test `tests/test_ui_app.py`, `tests/test_ops_views.py`.
**Interfaces:** `journal.days(paths) -> list[Path]`, `journal.read_day(path) -> list[Event]` (`read` uses both). `views._events` keeps a per-process cache `{path: ((st_size, st_mtime_ns), events)}` and re-reads only changed day files.
- [ ] Tests: `test_a_foreign_origin_is_refused` (POST with `Origin: http://evil.example` → 403; with `Origin: http://127.0.0.1:47123` → 200; without Origin → 200; system spec §10 "Host and Origin checks"); `test_past_journal_days_are_parsed_once` (two days of events; monkeypatch `journal.read_day` to count; two `views.overview` calls parse the past day once; an event appended today shows up in the second call's tail); run FAIL; implement; run PASS; commit `fix(ui): Origin check and a journal read cache`.

### Task 2: Comment-preserving settings writes
**Files:** Modify `settings.py`; Create `ops/configure.py`; Test `tests/test_settings_write.py`, `tests/test_ops_configure.py`.
**Interfaces:**
- `settings.set_values(paths, slug: str | None, changes: Mapping[str, Any]) -> list[str]` (dotted keys changed, in order; `None` removes the key from that scope's file; raises `UserError` with `_describe`'s text when the resolved result fails `Settings`, writing nothing). Scope file: `defaults/SETTINGS.md` for None, else `projects/<slug>/SETTINGS.md`; created with only the changed keys when missing.
- `settings.scope_keys(paths, slug) -> list[str]`: dotted leaf keys the scope's file sets (`workflows.<name>` counts as one leaf).
- `configure.save_settings(changes, *, project: str | None, by: str) -> Saved(project, keys)`: `settings.lock`, `set_values`, journal `settings.changed` (`project`, `keys`, `by`), store commit `harness: settings <scope>`; no-op saves journal nothing.
- Splice rule (the tests do not pin it): load the file with `YAML(typ="rt")` only to find line numbers. Walk the dotted key from the top: at each mapping try the longest dotted prefix present as a key (`loop_max.simple` before `loop_max`); descend only into block mappings. The entry where the walk stops (scalar, flow collection, or the key is missing) is the unit: rewrite just that entry's lines as `<indent><key>: <flow-dumped value>` keeping its trailing comment; a missing key is inserted after the last line of the block it belongs to (top level: end of file) as a dotted key; a flow map gets its leaf set or removed and is re-dumped on its own line. `workflows.<name>` is always replaced whole.
- [ ] Tests (`test_settings_write.py`, against a copy of the package default): `loop_max.simple: 5` changes exactly that line and keeps `# loops` and its neighbours; `agents.implementer.cli: claude/sonnet` changes only the implementer row (planner row identical, alignment kept); `merge.mode` absent from a project file is appended as `merge.mode: auto`; `workflows.standard` replaced whole on one line; `None` removes a project override and the resolved value falls back to the default; `loop_max.simple: 0` and `workflows.simple: {steps: [plan], on_fail: {review_code: plan}}` raise `UserError` and leave the bytes unchanged; `loop_maxx.simple` raises with `did you mean loop_max.simple`; two sequential saves of different keys keep both. `test_ops_configure.py`: journal `settings.changed` with `by: ui`, store committed, empty change set journals nothing. Run FAIL; implement; run PASS; commit `feat(settings): comment-preserving writes`.

### Task 3: Project settings screen
**Files:** Modify `ops/views.py`, `ui/app.py`, `ui/static/app.js`; Create `ui/static/views/settings.js`, `ui/static/scope.js` (scope tabs, set-here marks, dirty tracking, Save, Discard, shared by Tasks 3 to 5); Test `tests/test_ops_views.py`, `tests/test_ui_app.py`.
**Interfaces:** `views.settings(paths, *, project: str | None) -> SettingsView(scope, projects, values: dict[str, Any] (resolved, JSON), set_here: list[str], file: str, path: str, repo_path: str | None)`; `GET /api/settings?project=`, `POST /api/settings?project=` body `{changes: {...}}` → `SettingsView`.
- [ ] Tests: project scope marks only its overrides as set here; a POST with `loop_max.simple: 0` → 400 with `loop_max.simple` in the error and the file unchanged; Reset posts `null` for every `set_here` key. Screen per canvas: scope tabs (Defaults and each project, decision 8), Loop limits (`loop_max.*`, `loop_grant`, `loop_ask_at_cap`, `loop_count_rejected_review`), Token discipline (`skill.max_lines`, `skill.max_words`, `memory.compact_at_lines`, `review.diff_only`, `sessions.reuse`), Status flow (`status.names` in step order, read-only), SETTINGS.md view with set-here lines highlighted amber and both paths of the file, memory links summary reusing `/api/links` with Re-link and Adopt; run FAIL; implement; run PASS; commit `feat(ui): project settings screen`.

### Task 4: Agents and providers screen
**Files:** Modify `ops/views.py`, `ui/app.py`; Create `ui/static/views/agents.js`; Test `tests/test_ops_views.py`.
**Interfaces:** `views.providers(paths, *, project: str | None, window: Window, refresh: bool = False) -> AgentsView(providers: list[ProviderCard(name, installed, signed_in, version, hint, slots_used, slots_total, spend)], roster: list[Role(role, on, cli, provider, model, skill, blocking, fallback, used_in: list[str], tokens)], sessions_max, tokens_per_ticket, fallback_on_rate_limit, routing: dict[str, list[str]], set_here)`. Detection goes through `agents.detector`, cached per process for 60 s unless `refresh`; `used_in` lists workflows whose steps map to the role (`STEP_ROLES`); `tokens` sums `step.end` tokens per `role` in the window. `GET /api/providers?project=&window=&refresh=`.
- [ ] Tests: role tokens summed per role; `used_in` empty for a role in no workflow; a second call within 60 s does not detect again (count calls on a fake detector); signed-out provider carries its hint. Screen: provider cards (signed in, slots, spend, "Sign in" shows the hint command, never runs it), roster toggles and CLI·model inputs, limits (`sessions.max`, `tokens.per_ticket_max`, `fallback_on_rate_limit`, `sessions.per_provider.*`), importance routing with a link to the Workflow editor; saves through `POST /api/settings`; run FAIL; implement; run PASS; commit `feat(ui): agents and providers screen`.

### Task 5: Workflow editor
**Files:** Modify `ops/views.py`, `ui/app.py`; Create `ui/static/views/workflow.js`, `ui/static/graph.js` (left-to-right SVG layout: trigger, steps, done; solid pass edges, dashed `on_fail` edges labelled "send back"); Test `tests/test_ops_views.py`, `tests/test_ui_static.py`.
**Interfaces:** `views.workflows(paths, *, project: str | None) -> WorkflowsView(names, workflows: dict[str, Workflow], effective: dict[str, list[str]] (`workflow.steps_for(settings, name, hitl=False)`), loop_max: dict[str, int], loop_ask_at_cap, agents: dict[str, str] (role → cli), library: list[str] (`STEP_ROLES`), set_here)`; `GET /api/workflows?project=`.
- [ ] Tests: `effective` drops a step whose agent is off; the graph module lays out N steps in N+2 columns with one dashed edge per `on_fail` entry (node, when present). Screen: tabs per workflow, graph, selected-step panel (role, CLI·model, skill, `on_fail` target among this workflow's steps or none, max loops), node library (add a step), move left or right, remove, loop guard rails, "Dry run" shows `effective`; Save posts `workflows.<name>` whole plus changed `loop_max.*` and `agents.<role>.cli`; run FAIL; implement; run PASS; commit `feat(ui): workflow editor`.

### Task 6: Ticket detail
**Files:** Modify `ops/views.py`, `ui/app.py`; Create `ui/static/views/ticket.js`; Test `tests/test_ops_views.py`, `tests/test_ui_app.py`.
**Interfaces:** `views.ticket(paths, ticket_id, *, project: str | None) -> TicketView(meta: dict, sections: dict[str, str], file: str, store_path, repo_path, plan: PlanRef(id, title, prompt, found), siblings: list[TicketLink(id, title, status)], depends_on: list[TicketLink], blocks: list[TicketLink], changes: list[Change] (empty without a branch), timeline: list[TimelineStep(ts, step, role, provider, model, verdict, loop, tokens, duration_s)], memory_writes: list[dict] (`memory.write` events whose `ticket` is this id or whose `why` names it), chain: list[ChainStep(step, role, runs, state)], attach: str)`; `GET /api/tickets/{id}`, `GET /api/tickets/{id}/diff` (`changes.ticket_changes(diff=True)`), `GET /api/plans/{id}`.
- [ ] Tests: sparse ticket (no events, no plan file, no branch) → empty lists and `plan.found` false; `blocks` lists tickets that depend on this one; timeline from `step.start`/`step.end` pairs in order. Screen per canvas: header (importance, status, loop with Grant +2 at a gate, project, worktree, opened), tabs Overview · Changes · Timeline · Ticket file, findings, prompt with plan link, acceptance, dependencies, memory writes, agent chain, metadata, attach command (copy), Run, Park (an inline why field, never `window.prompt`), Stop, Merge (awaiting_merge), Send back to in_queue, Force move to done (second click); actions use M1's `POST /api/tickets/{id}/{action}`; run FAIL; implement; run PASS; commit `feat(ui): ticket detail`.

### Task 7: Memory store screen
**Files:** Modify `ops/views.py`, `ui/app.py`, `ui/static/views/memory.js`; Test `tests/test_ops_views.py`, `tests/test_ui_app.py`.
**Interfaces:** `views.memory(paths) -> MemoryView(size_bytes, ticket_files, md_files, tickets: dict[str, int] (per folder), links: Links, files: list[MemoryFile(name, scope, lines, entries, tokens (chars/4), compacted)], memory_text, cap, compacting: bool, index: list[IndexRow(id, title, project, status, loop, loop_max, models, closed)], writes: list[dict] (last 30 `memory.write`/`memory.compacted`/`ticket.moved`))`; `GET /api/memory`, `POST /api/memory/compact` → `{started}` (`compaction.start_background`; the screen refreshes on `memory.compacted`).
- [ ] Tests: empty store → zero stats, no rows; models in the index come from `step.end` per ticket; compact POST starts the job once (a running job → `started` true, no second job). Screen per canvas: backend panel (markdown active; sqlite index, vector recall "planned"), stat tiles, files table, MEMORY.md view with cap bar and Compact, link health (M1), ticket index with All · Running · Done and a find box, writes to memory; run FAIL; implement; run PASS; commit `feat(ui): memory store screen`.

### Task 8: Chrome pass
- [ ] Extend `scripts/demo_store.py` (a project with overrides in SETTINGS.md, sessions on a ticket, memory writes, a branch with changes). With the demo store, check every M2 screen against its canvas board in Chrome: layout, numbers, each action and save (then `git -C <store> diff` shows only the changed lines), live refresh. Findings become tests where they can; commit `fix(ui): M2 Chrome pass`.

### Task 9: Docs and review
- [ ] Module docs (`ui`, `ops`, `settings`, `journal`), `docs/architecture.md`, AGENTS.md status, spec §4 rows for canvas elements found unlisted (e.g. Agents "New agent", Settings "Prefer shell commands over prose", Status flow "add"); `make check`; review the M2 diff against the spec and the Review Focus; commit `docs: SP5 M2 built`.
