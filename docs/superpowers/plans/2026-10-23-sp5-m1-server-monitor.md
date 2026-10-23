# SP5 M1: Server and Monitor Screens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `harness ui open` serves a token-protected local app whose Overview and Task board show the store live, matching the canvas.

**Architecture:** `ops.views` builds read models (dataclasses) from the store, runtime and journal. `ui` is a FastAPI app over those views and the existing `ops` actions, with cookie-token auth, a Host check and SSE from the journal. `ops.ui_server` starts, reuses and stops the detached server. The frontend is plain ES modules under `ui/static/` with a hash router.

**Tech Stack:** FastAPI, uvicorn (the `[ui]` extra), httpx2 (`TestClient`, dev; Starlette 1.9 replaced httpx with it), plain JavaScript and CSS; Chrome through the Claude in Chrome extension for screen checks.

**Spec:** `docs/superpowers/specs/2026-10-23-sp5-ui-design.md` (decisions 1–6, 8, 9, 11; §3; §4 rows "all", "Overview", "Task board").

## Global Constraints

- `ui` imports only `ops` and `model`; layers become `cli | worker | ui > ops > …`.
- Colours, type and spacing follow the canvas: background `#0E1012`, panels `#16191D`, raised `#1C2026`, borders `#262B32`, text `#ECEFF3`, muted `#A7B0BC` and `#78828F`, accent `#F0883E` (hover `#FFA463`); Inter and JetBrains Mono with system fallbacks; nothing fetched from the network.
- Every rendered string is escaped; no `innerHTML` with unescaped data.
- Module docs change with modules; commits end with the Co-Authored-By line.

## Review Focus

1. A request with no token, a wrong token, a foreign `Host` header, or a `POST` without `X-Harness` gets 401/403 (Task 3).
2. `harness ui open` twice reuses the running server and prints the same URL; a dead `ui.json` pid starts a new one (Task 4).
3. A ticket title holding `<script>` renders as text (Task 5).
4. An empty store (no projects) renders every screen with empty states, not errors (Tasks 2, 5).
5. The SSE stream ends cleanly when the browser goes away and never blocks other requests (Task 3).

---

### Task 1: Dependencies and the layer contract
- [ ] `uv add --optional ui fastapi uvicorn`; `uv add --dev fastapi uvicorn httpx2`; import-linter: `ui` in the top layer beside `cli` and `worker`, and a contract that `ui` reaches the store only through `ops`; `docs/modules/ui/README.md`; `make check`; commit `build: the [ui] extra and the ui layer`.

### Task 2: Read models for Overview and Task board
**Files:** Create `src/super_harness/ops/views.py`, `tests/test_ops_views.py`.
**Interfaces:**
- `views.overview(paths: StorePaths, *, window: Literal["today", "7d", "all"]) -> Overview` with `projects: list[str]`, `sessions: list[Session(ticket, project, step, status, provider, model, loop, loop_max, since)]` (in_process tickets running a step, provider and model from `TicketState.running` or the step's agent), `queue: Counts(ready, blocked, parked, parallel, serial)`, `gates: list[Gate(ticket, project, status, title, loop, loop_max, reason)]`, `done_today: int`, `slots: list[Slot(provider, used, total)]`, `spend: dict[str, int]` (tokens from `step.end` in the window), `conductors: list[ConductorPing]` (fresh in the last 10 minutes), `tail: list[Event]` (the last 30).
- `views.board(paths, *, project: str | None) -> Board` with `columns: list[Column(key, title, cards: list[Card(id, project, title, importance, status, step, loop, loop_max, provider, parallel, added, removed, findings, updated)])]`; columns: In queue, Planning, Plan review, Implementing, Code review, Security, Tests, Docs, Waiting (waiting_slot, waiting_quota, paused), Needs you (needs_approval, stalled, failed, awaiting_merge), Done.
- [ ] Tests on a seeded store (fixtures): empty store, gates and sessions counted, spend summed per provider and window, cards in the right columns with diff sizes from `step.end` events; run FAIL; implement; run PASS; commit `feat(ops): read models for the overview and the board`.

### Task 3: The FastAPI app
**Files:** Create `src/super_harness/ui/__init__.py`, `ui/app.py`, `ui/__main__.py`, `ui/static/index.html`; Test `tests/test_ui_app.py`.
**Interfaces:** `ui.app.create_app(*, token: str, port: int) -> FastAPI`: `GET /` (with `?token=` sets the cookie and redirects to `/`; without a valid cookie returns a plain "open the link `harness ui open` printed" page with 401), `GET /static/*`, `GET /api/overview`, `GET /api/board`, `GET /api/events` (SSE: `event: journal` with the event JSON; `: ping` every 15 s), `POST /api/pause`, `POST /api/resume`. Auth middleware per decision 4. `python -m super_harness.ui --port N` reads the token from `HARNESS_UI_TOKEN`.
- [ ] Tests (`TestClient`): token cookie flow and redirect; 401 without or with a wrong token; 403 for a foreign Host; 403 for a POST without `X-Harness`; overview and board JSON shapes; SSE delivers an event appended after the stream opens (read with a short timeout); run FAIL; implement; run PASS; commit `feat(ui): token-protected API with a journal event stream`.

### Task 4: `harness ui open|stop`
**Files:** Create `src/super_harness/ops/ui_server.py`; Modify `cli.py`, `store/paths.py` (`ui_file`); Test `tests/test_ops_ui_server.py`, `tests/test_cli_ui.py`.
**Interfaces:** `ui_server.open_ui(*, browser: bool) -> UiServer(url, pid, port, reused)` (`NeedsSetup` without fastapi or uvicorn; waits up to 10 s for the port to answer), `ui_server.stop_ui() -> bool`. CLI `harness ui open [--no-browser] [--json]` prints the URL; `harness ui stop` prints `stopped` or `not running`.
- [ ] Tests: start, reuse (same URL), stale record restarts, stop; missing extra → exit 4 with the install line (simulate by monkeypatching the import check); run FAIL; implement; run PASS; commit `feat: harness ui open and stop`.

### Task 5: App shell, Overview and Task board
**Files:** Create `ui/static/{app.css,app.js,api.js,html.js,views/overview.js,views/board.js}`, `scripts/demo_store.py` (a seeded store: three projects, plans, tickets in every column, journal events with tokens); Test `tests/test_ui_static.py` (assets served; `html.js` escapes, checked by running node when present, else skipped).
- [ ] Shell: sidebar sections OPERATE (Overview, Task board), ORCHESTRATE (Workflow, Agents), PROJECT (Memory, Settings) with counts, CLI pool, version; top bar with project filter and search; hash routes; SSE subscription that refetches the current view. Overview and Board per canvas. Run `scripts/demo_store.py`, `harness ui open`, check both screens in Chrome (layout, numbers, live update after `harness ticket move`), fix findings; commit `feat(ui): app shell, overview and task board`.

### Task 6: Docs and review
- [ ] Module docs (`ui`, `ops`, `cli`, `store`), architecture, `make check`; review the M1 diff against the spec and the Review Focus; commit `docs: SP5 M1 built`.
