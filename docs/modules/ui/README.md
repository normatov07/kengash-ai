# ui

## Purpose

The local web UI (SP5 spec; system spec §9): a FastAPI app on `127.0.0.1` that serves the static screens, a JSON API over `ops` and a server-sent event stream of the journal. Needs the `[ui]` extra (`fastapi`, `uvicorn`).

## Interface

- `python -m super_harness.ui --port N`, token in `HARNESS_UI_TOKEN` (popped from the environment); started by `harness ui open` (`ops.ui_server`).
- `app.create_app(token=, port=)`: `GET /` (`?token=` sets an `HttpOnly`, `SameSite=Strict` cookie and redirects to `/`; otherwise 401 without it), `/static/*`, `GET /api/overview?window=today|7d|all`, `GET /api/board?project=`, `POST /api/pause|resume?project=`, `POST /api/tickets/{id}/approve|park|run|stop|merge|move` (body `{loops, tokens, why, to}`; each action reads what it needs), `GET /api/events` (SSE `event: journal` per new journal line, `: ping` every 15 s; `app.event_stream`). Harness errors come back as `{"error": …}`: 400, or 409 for setup and user decisions.

- `static/`: `index.html`, `fonts/` (Inter and JetBrains Mono latin woff2, `OFL.txt`), `icons.js` (the canvas's icons, `icon(name, {size, stroke, width, label})`, `STEP_ICONS`), `app.css` (the canvas tokens and step colours, dark scrollbars, `.select`, `.switch`, `.tabs-line`, `.foot-card`, `.pill`), `app.js` (sidebar with counts (tickets, agents on/total, broken links) and a live dot; each screen may export `top(data, app)` for its own top bar and `foot(data, app)` for its sidebar card, else the default top bar (project filter, search, `/to-ticket`, `/to-loop`) and none; `bind(root, app, data, bar)` gets the top bar too; hash routes; the nav follows the route before data arrives; refresh on journal events), `api.js`, `html.js` (templates that escape every value), `format.js`, `views/overview.js` (canvas board Main: tiles, live sessions in step colours with a two-click stop per row, approvals by gate kind with their action, token spend with the average ticket cost, the loop journal as one humanised line per event with Follow tail, the CLI pool as its sidebar card, and a banner while any folder link needs a fix), `views/board.js`, `views/memory.js` (link health per project with Repair, Re-link and a two-click Adopt; stores found nearby). Other routes show a placeholder until M2.
- `GET /api/settings?project=` → `SettingsView` (empty `project` is the defaults); `POST /api/settings?project=` `{changes: {dotted.key: value|null}}` saves through `ops.configure` and answers with the new view.
- `scope.js`: the configure screens' scope tabs, fields with set-here marks, Save · Discard · Reset (Reset and other destructive buttons act on a second click within 4 s); while a form has unsaved edits (`app.dirty`) journal events do not re-render it. `views/settings.js`: loop limits, token discipline, project commands (`project.test_cmd`, `project.lint_cmd`), status flow, SETTINGS.md with this scope's overrides in amber and both paths, memory links.
- `GET /api/agents?project=&window=&refresh=` → `AgentsView`; `views/agents.js`: provider cards (Sign in or Install copy the CLI's own command; harness never runs it), the roster (on/off, CLI·model, skill file, used in, tokens), limits and per-provider sessions, importance routing; saves through `/api/settings`. A route whose data takes over 400 ms shows Loading.
- `GET /api/workflows?project=` → `WorkflowsView`; `graph.js` (`layout(steps, on_fail)`: trigger, steps, done left to right; `svg(graph, {selected, sub, off})`); `views/workflow.js`: workflow tabs, the graph, the selected step (its agent's CLI, where a failing verdict sends it, move, remove), the step library, a dry run of the steps that would run, loop guard rails; a save writes each edited `workflows.<name>` whole.
- `GET /api/tickets/{id}` → `TicketView`; `GET /api/tickets/{id}/diff` → the ticket's `Changes` with the diff; `GET /api/plans/{id}` → `{project, meta, sections}`. `views/ticket.js` (`#/ticket/<id>`): header with the gate's action (Grant +N loops, Merge, Run again), tabs Overview · Changes · Timeline · Ticket file, findings, prompt with the plan on demand, acceptance, dependencies, memory writes, agent chain, metadata, attach command, Stop, Park with a why, Send back to in_queue, Force move to done (second click).
- `GET /api/memory?project=` → `MemoryView`; `POST /api/memory/compact` → `{started}` (`compaction.start_checked`; the screen refreshes on `memory.compacted`). `views/memory.js`: backends (markdown active; sqlite index and vector recall planned), store tiles, memory files, MEMORY.md with its cap and Compact, link health and stores found nearby, the ticket index with All · Running · Done and a find box, writes to memory.
- `GET /api/meta` → `{version}`. `GET /api/links` (link health); `POST /api/links/repair` (`harness doctor --fix`), `POST /api/links/relink` `{project, path}`, `POST /api/links/adopt` `{path}`; each answers with the new link health.

## Invariants

- Imports only `ops` and `model` (import-linter); every action goes through `ops` with `by="ui"`.
- No network fetches, no build step: the screens are static ES modules and one stylesheet.
- Every `/api` request needs the run's token; foreign `Host` and `Origin` headers are refused (system spec §10); `POST` needs `X-Harness: 1`.

## Changes

- 2026-10-24: canvas parity foundation: bundled fonts, icons, tokens, per-screen top bar and sidebar card slots.
- 2026-10-24: M2 Chrome pass: table headers in one type, memory lines without their bullet, project commands on Settings.
- 2026-10-23: Memory store, Ticket detail, Settings, Agents and Workflow screens, scope tabs and settings saves (SP5 M2).
- 2026-10-23: requests with a foreign `Origin` are refused (SP5 M2).
- 2026-10-23: link health on the Memory screen, link banner on the Overview (system spec §4.2).
- 2026-10-23: app shell, Overview and Task board (SP5 M1).
- 2026-10-23: the `ui` unit and its layer contract (SP5 M1).
