# Sub-project 5: Web UI — Spec

- Date: 2026-10-23
- Status: approved by default (user prefers momentum; assumptions listed in §2 for veto)
- Implements: system spec `2026-10-22-super-harness-design.md` §9 (UI), §6 (`harness ui open|stop`), §13 row 5, the `open-ui` skill (§8.1, moved here by the SP4 spec); the Claude Design canvas `https://claude.ai/artifact/JiMGMkbaw8qhafeaNbqU7d` (seven boards: Overview, Task board, Ticket detail, Workflow editor, Agents and providers, Project settings, Memory store).
- This spec only adds what the system spec leaves open; where the canvas and the system spec differ, the system spec wins (§4 lists each case).

## 1. Milestones

| # | Milestone | Delivers | Exit |
|---|---|---|---|
| M1 | Server and monitor screens | the `ui` unit (FastAPI app, token auth, SSE), `harness ui open\|stop`, the `[ui]` extra, read models in `ops.views`, the app shell, Overview and Task board | API tests pass; Overview and Task board match the canvas in Chrome against a seeded store; live updates arrive over SSE |
| M2 | Inspect and configure screens | Ticket detail with its actions, Workflow editor, Agents and providers, Project settings, Memory store; comment-preserving settings writes | every canvas action that maps to an `ops` call works from the UI (checked in Chrome); settings edits keep comments |
| M3 | `open-ui` and parity | the `open-ui` skill with its eval, the parity checklist (§4) closed, docs | checklist complete; eval green on claude and agy; `make check` green |

## 2. Decisions (assumed defaults — veto any)

1. **No frontend build.** The UI is static ES modules and one stylesheet in `src/super_harness/ui/static/`, shipped in the wheel: plain JavaScript with a small escaping template helper, no npm, no bundler, no CDN. Fonts fall back to the system's (`Inter`, then `system-ui`; `JetBrains Mono`, then `ui-monospace`); nothing is fetched from the network.
2. **Optional extra.** `fastapi` and `uvicorn` are the `[ui]` extra. Without them `harness ui open` exits 4 with `install the UI: uv tool install --force 'super-harness[ui] @ git+https://github.com/normatov07/super-harness'`.
3. **One detached server.** `harness ui open` starts `python -m super_harness.ui` (`start_new_session`) on `127.0.0.1` and a free port, records `runtime/ui.json` (`pid`, `port`, `token`, `started`), and reuses a live one. It prints `http://127.0.0.1:<port>/?token=<token>` and opens the browser unless `--no-browser`. `harness ui stop` ends it. The server is not a loop daemon: it only reads and acts through `ops`, and nothing depends on it running.
4. **Auth.** A random 32-byte token per server. The first page load with `?token=` sets an `HttpOnly`, `SameSite=Strict` cookie and redirects to strip the token from the URL; every `/api` request needs the cookie (or `Authorization: Bearer`). Requests whose `Host` is not `127.0.0.1:<port>` or `localhost:<port>` are refused (DNS rebinding). State-changing requests are `POST` and also need the `X-Harness: 1` header.
5. **Layers.** `ui` imports only `ops` and `model` (import-linter). Read models live in `ops.views` (dataclasses, built from the store, runtime and journal); actions call the existing `ops` functions with `by="ui"`.
6. **Live updates.** `GET /api/events` is a server-sent event stream: one `journal` event per new journal line (from `journal.read_after`, polled every second), with a heartbeat comment every 15 s. Screens refetch what an event touches.
7. **Comment-preserving settings writes.** `settings.set_values(paths, slug|None, changes)` edits SETTINGS.md with ruamel round-trip YAML, validates the result against `Settings` before writing, and journals `settings.changed`; the Workflow, Agents and Settings screens all save through it. A save never rewrites keys it did not change.
8. **Scope switch.** Configure screens edit the defaults or one project (the canvas's "Defaults · payments-api · web-dashboard" tabs); values set in the shown scope are highlighted, the rest are inherited.
9. **Token spend** is summed from `step.end` journal events (`tokens.in + tokens.out`) per provider for the chosen window (today, 7 days, all).
10. **Workflow editor.** The graph is drawn from `workflows.<name>` (`steps` in order, `on_fail` edges dashed). Edits are structural, not free-form: reorder or remove steps, add a step from the library, retarget a step's `on_fail`, change `loop_max.<importance>`, and pick each step's agent. The canvas's free node positions are not stored (system spec settings have none): layout is automatic, left to right.
11. **Chrome checks.** Each milestone ends with a pass in the user's Chrome through the Claude in Chrome extension against a seeded demo store (`harness ui open` with `HARNESS_HOME` pointing at a store built by `scripts/demo_store.py`); findings become tests where they can.
12. **Link health** (system spec §4.2). The Memory screen shows, per project, the repo's folder link, the project's memory link and the exclude entry, each `ok` or what is wrong, with the one action that fixes it: Repair (`doctor --fix`), Re-link a moved repo to a path the user types (`harness link`), or Adopt the repo's own `.harness/` folder (`harness adopt`, confirmed by a second click). It also lists real `.harness/` folders found beside registered repos ("stores found nearby") with Adopt. The Overview shows a banner while any link is broken; the Settings and Ticket screens say "folder link" and show both paths of a file.
13. **`open-ui`** runs `harness ui open`; on exit 4 it asks the user to install the UI extra, installs it on yes, and opens again.

## 3. Units and API

| Unit | Holds | May import |
|---|---|---|
| `ui` | FastAPI app, auth, SSE, static assets, `python -m super_harness.ui` | `ops`, `model` |
| `ops` (adds `views`, `ui_server`) | read models for each screen; start, reuse and stop the server | as before |
| `settings` (adds writes) | comment-preserving `set_values` | `model`, `store` |

Endpoints (all JSON; `POST` bodies are JSON):

| Method and path | Backed by |
|---|---|
| `GET /api/overview?window=today\|7d\|all` | `views.overview`: projects, live sessions (workers and their steps), queue counts, gates, CLI pool (slots per provider), token spend, conductors, journal tail |
| `GET /api/board?project=` | `views.board`: tickets grouped by column (in_queue, each in_process step, gates, done) |
| `GET /api/tickets/{id}` | `views.ticket`: frontmatter, sections, plan prompt and acceptance, changes, step timeline (journal), sessions, dependencies, memory writes |
| `POST /api/tickets/{id}/{run\|approve\|park\|stop\|merge\|move}` | `controls`, `merging`, `tickets.move_ticket` |
| `GET /api/plans/{id}` | `plans.show_plan` |
| `GET /api/settings?project=` · `POST /api/settings?project=` | `views.settings` (resolved values, which scope set each, the raw file) · `settings.set_values` |
| `GET /api/providers` | `views.providers`: detection, sign-in, slots, spend |
| `GET /api/memory` · `POST /api/memory/compact` · `POST /api/links/repair` | `views.memory` (files, caps, links, ticket index, memory writes) · `compaction.compact_memory` · `projects.doctor(fix=True)` |
| `POST /api/pause` · `POST /api/resume` | `controls.pause`, `controls.resume` |
| `GET /api/events` | journal tail as SSE |

## 4. Parity checklist (canvas → build)

Each canvas element is built, built differently because the system spec says otherwise, or left out because nothing in the system backs it. M3 closes the list.

| Screen | Built | Built differently | Left out |
|---|---|---|---|
| all | sidebar (Overview, Task board, Workflow, Agents, Memory, Settings) with counts; CLI pool; search (`ticket find`); `/to-ticket` and `/to-loop` hints | "loop engine running" → live conductors (system spec §9) | — |
| Overview | stat tiles, live sessions table, approvals with Grant loops / Park, token spend, journal tail with follow; window Today · 7 days · All; Pause all | "PLAN STALLED: read both plans" → links to the ticket's plan and Findings | "avg skill read" (not measured) |
| Task board | columns per status with counts, cards (importance, parallel or serial, loop, provider, diff size, findings), group by status | "wip cap" → the step's slot use | "Add ticket" (tickets come from `/to-ticket`) |
| Ticket detail | header with actions, changes table and diff, findings, prompt, acceptance, dependencies, step timeline, ticket file, memory writes, agent chain, metadata, attach command, send back, force move | "Reveal hard link" → both paths of the ticket file: the store's and the repo's through its folder link | — |
| Workflow editor | per-importance tabs, graph, selected step panel (agent, model, skill, on_fail target), node library, loop guard rails, save to SETTINGS.md | free node positions → automatic layout; "Dry run" → shows the effective steps | "Drag from a port" (retarget from the panel instead) |
| Agents | providers with sign-in, slots, spend; roster with on/off, CLI and model, skill, used in, tokens; limits; importance routing | "Sign in" → the command to run (harness never signs in for you) | "Kill the session when a ticket stalls over 30 minutes" (no such setting) |
| Settings | loop limits, token discipline, status flow, SETTINGS.md view with set-here highlighting, memory links summary with Re-link and Adopt (decision 12) | "hard-linked" → "linked by one folder link" (system spec §4.2) | — |
| Memory | store stats, memory files table, MEMORY.md view with compact, link health per project (folder link, memory link, exclude entry) with Repair, Re-link and Adopt, stores found nearby, ticket index, memory writes | "HARD LINKS n/m" → "FOLDER LINKS n/m"; "Adopt by hard link" → Adopt (`harness adopt`); backend "sqlite index", "vector recall" shown as planned | "Retention" options (no such settings) |

## 5. Acceptance (SP5 exit)

- [ ] `harness ui open` starts or reuses the server, prints the URL, opens the browser; `harness ui stop` ends it; without the extra it exits 4 naming the install command.
- [ ] Requests without the token, with a foreign `Host`, or a `POST` without `X-Harness` are refused.
- [ ] The seven screens render a seeded store in Chrome and update live over SSE.
- [ ] Every UI action goes through `ops` (import-linter keeps `ui` off the store) and is journaled with `by: ui`.
- [ ] Settings saves keep comments and untouched keys.
- [ ] The parity checklist (§4) is complete; the `open-ui` eval passes on claude and agy.
