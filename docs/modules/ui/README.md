# ui

## Purpose

The local web UI (SP5 spec; system spec §9): a FastAPI app on `127.0.0.1` that serves the static screens, a JSON API over `ops` and a server-sent event stream of the journal. Needs the `[ui]` extra (`fastapi`, `uvicorn`).

## Interface

- `python -m super_harness.ui --port N`, token in `HARNESS_UI_TOKEN` (popped from the environment); started by `harness ui open` (`ops.ui_server`).
- `app.create_app(token=, port=)`: `GET /` (`?token=` sets an `HttpOnly`, `SameSite=Strict` cookie and redirects to `/`; otherwise 401 without it), `/static/*`, `GET /api/overview?window=today|7d|all`, `GET /api/board?project=`, `POST /api/pause|resume?project=`, `POST /api/tickets/{id}/approve|park|run|stop|merge|move` (body `{loops, tokens, why, to}`; each action reads what it needs), `GET /api/events` (SSE `event: journal` per new journal line, `: ping` every 15 s; `app.event_stream`). Harness errors come back as `{"error": …}`: 400, or 409 for setup and user decisions.

- `static/`: `index.html`, `app.css` (the canvas tokens), `app.js` (sidebar with counts and the CLI pool, top bar with project filter, search and the `/to-ticket` and `/to-loop` hints, hash routes, refresh on journal events), `api.js`, `html.js` (templates that escape every value), `format.js`, `views/overview.js`, `views/board.js`. Other routes show a placeholder until M2.
- `GET /api/meta` → `{version}`.

## Invariants

- Imports only `ops` and `model` (import-linter); every action goes through `ops` with `by="ui"`.
- No network fetches, no build step: the screens are static ES modules and one stylesheet.
- Every `/api` request needs the run's token; foreign `Host` headers are refused; `POST` needs `X-Harness: 1`.

## Changes

- 2026-10-23: app shell, Overview and Task board (SP5 M1).
- 2026-10-23: the `ui` unit and its layer contract (SP5 M1).
