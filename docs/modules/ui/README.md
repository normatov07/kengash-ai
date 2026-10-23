# ui

## Purpose

The local web UI (SP5 spec; system spec §9): a FastAPI app on `127.0.0.1` that serves the static screens, a JSON API over `ops` and a server-sent event stream of the journal. Needs the `[ui]` extra (`fastapi`, `uvicorn`).

## Interface

- `python -m super_harness.ui --port N`, token in `HARNESS_UI_TOKEN` (popped from the environment); started by `harness ui open` (`ops.ui_server`).
- `app.create_app(token=, port=)`: `GET /` (`?token=` sets an `HttpOnly`, `SameSite=Strict` cookie and redirects to `/`; otherwise 401 without it), `/static/*`, `GET /api/overview?window=today|7d|all`, `GET /api/board?project=`, `POST /api/pause|resume?project=`, `POST /api/tickets/{id}/approve|park|run|stop|merge|move` (body `{loops, tokens, why, to}`; each action reads what it needs), `GET /api/events` (SSE `event: journal` per new journal line, `: ping` every 15 s; `app.event_stream`). Harness errors come back as `{"error": …}`: 400, or 409 for setup and user decisions.

- `static/`: `index.html`, `app.css` (the canvas tokens), `app.js` (sidebar with counts and the CLI pool, top bar with project filter, search and the `/to-ticket` and `/to-loop` hints, hash routes, refresh on journal events), `api.js`, `html.js` (templates that escape every value), `format.js`, `views/overview.js` (with a banner while any folder link needs a fix), `views/board.js`, `views/memory.js` (link health per project with Repair, Re-link and a two-click Adopt; stores found nearby). Other routes show a placeholder until M2.
- `GET /api/settings?project=` → `SettingsView` (empty `project` is the defaults); `POST /api/settings?project=` `{changes: {dotted.key: value|null}}` saves through `ops.configure` and answers with the new view.
- `scope.js`: the configure screens' scope tabs, fields with set-here marks, Save · Discard · Reset (Reset and other destructive buttons act on a second click within 4 s); while a form has unsaved edits (`app.dirty`) journal events do not re-render it. `views/settings.js`: loop limits, token discipline, status flow, SETTINGS.md with this scope's overrides in amber and both paths, memory links.
- `GET /api/meta` → `{version}`. `GET /api/links` (link health); `POST /api/links/repair` (`harness doctor --fix`), `POST /api/links/relink` `{project, path}`, `POST /api/links/adopt` `{path}`; each answers with the new link health.

## Invariants

- Imports only `ops` and `model` (import-linter); every action goes through `ops` with `by="ui"`.
- No network fetches, no build step: the screens are static ES modules and one stylesheet.
- Every `/api` request needs the run's token; foreign `Host` and `Origin` headers are refused (system spec §10); `POST` needs `X-Harness: 1`.

## Changes

- 2026-10-23: Settings screen, scope tabs and settings saves (SP5 M2).
- 2026-10-23: requests with a foreign `Origin` are refused (SP5 M2).
- 2026-10-23: link health on the Memory screen, link banner on the Overview (system spec §4.2).
- 2026-10-23: app shell, Overview and Task board (SP5 M1).
- 2026-10-23: the `ui` unit and its layer contract (SP5 M1).
