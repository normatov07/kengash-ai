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

1. **No frontend build.** The UI is static ES modules and one stylesheet in `src/super_harness/ui/static/`, shipped in the wheel: plain JavaScript with a small escaping template helper, no npm, no bundler, no CDN. Inter and JetBrains Mono ship with it as latin woff2 files under the SIL Open Font License (`static/fonts/OFL.txt`), so the screens look like the canvas on every machine; nothing is fetched from the network.
2. **Optional extra.** `fastapi` and `uvicorn` are the `[ui]` extra. Without them `harness ui open` exits 4 with `install the UI: uv tool install --force 'super-harness[ui] @ git+https://github.com/normatov07/super-harness'`.
3. **One detached server.** `harness ui open` starts `python -m super_harness.ui` (`start_new_session`) on `127.0.0.1` and a free port, records `runtime/ui.json` (`pid`, `port`, `token`, `started`), and reuses a live one. It prints `http://127.0.0.1:<port>/?token=<token>` and opens the browser unless `--no-browser`. `harness ui stop` ends it. The server is not a loop daemon: it only reads and acts through `ops`, and nothing depends on it running.
4. **Auth.** A random 32-byte token per server. The first page load with `?token=` sets an `HttpOnly`, `SameSite=Strict` cookie and redirects to strip the token from the URL; every `/api` request needs the cookie (or `Authorization: Bearer`). Requests whose `Host` is not `127.0.0.1:<port>` or `localhost:<port>` are refused (DNS rebinding). State-changing requests are `POST` and also need the `X-Harness: 1` header.
5. **Layers.** `ui` imports only `ops` and `model` (import-linter). Read models live in `ops.views` (dataclasses, built from the store, runtime and journal); actions call the existing `ops` functions with `by="ui"`.
6. **Live updates.** `GET /api/events` is a server-sent event stream: one `journal` event per new journal line (from `journal.read_after`, polled every second), with a heartbeat comment every 15 s. Screens refetch what an event touches.
7. **Comment-preserving settings writes.** `settings.set_values(paths, slug|None, changes)` edits SETTINGS.md with ruamel round-trip YAML, validates the result against `Settings` before writing (a save to the defaults also resolves every registered project with the new defaults and is refused, naming the project and its first problem, when one that validated before would not), and journals `settings.changed`; the Workflow, Agents and Settings screens all save through it. A save never rewrites keys it did not change, and the lines it writes keep the file's line ending (CRLF stays CRLF).
8. **Scope switch.** Configure screens edit the defaults or one project (the canvas's "Defaults · payments-api · web-dashboard" tabs); values set in the shown scope are highlighted, the rest are inherited.
9. **Token spend** is summed from `step.end` journal events (`tokens.in + tokens.out`) per provider for the chosen window (today, 7 days, all).
10. **Workflow editor.** The graph is drawn from `workflows.<name>` (`steps` in order, `on_fail` edges dashed). Edits are structural, not free-form: reorder or remove steps, add a step from the library, retarget a step's `on_fail`, change `loop_max.<importance>`, and pick each step's agent. The canvas's free node positions are not stored (system spec settings have none): layout is automatic, top to bottom as on the canvas, with send-back edges routed to the right and a zoom control.
11. **Chrome checks.** Each milestone ends with a pass in the user's Chrome through the Claude in Chrome extension against a seeded demo store (`harness ui open` with `HARNESS_HOME` pointing at a store built by `scripts/demo_store.py`); findings become tests where they can.
12. **Link health** (system spec §4.2). The Memory screen shows, per project, the repo's folder link, the project's memory link and the exclude entry, each `ok` or what is wrong, with the one action that fixes it: Repair (`doctor --fix`), Re-link a moved repo to a path the user types (`harness link`), or Adopt the repo's own `.harness/` folder (`harness adopt`, confirmed by a second click). It also lists real `.harness/` folders found beside registered repos ("stores found nearby") with Adopt. The Overview shows a banner while any link is broken; the Settings and Ticket screens say "folder link" and show both paths of a file.
13. **`open-ui`** runs `harness ui open`; on exit 4 it asks the user to install the UI extra, installs it on yes, and opens again.
14. **Canvas parity.** Each screen ports its canvas board: its own top bar (the default one is the project filter, search, `/to-ticket` and `/to-loop`) and sidebar footer card (CLI pool on the Overview, importance legend on the Task board, backends on the Memory store), the canvas's tokens and step colours, and its regions bound to `/api` data. The ticket opens as a sheet over the dimmed page and closes back to where it was opened. On the Task board a ticket at a gate or waiting for a slot stays in its step's column with a chip naming why.

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
| `GET /api/tickets/{id}` · `GET /api/tickets/{id}/diff` | `views.ticket_view`: frontmatter, sections, plan prompt and acceptance, changes, step timeline (journal), sessions, dependencies, memory writes, agent chain · `changes.ticket_changes(diff=True)` |
| `POST /api/tickets/{id}/{run\|approve\|park\|stop\|merge\|move}` | `controls`, `merging`, `tickets.move_ticket` |
| `GET /api/plans/{id}` | `plans.show_plan` |
| `GET /api/settings?project=` · `POST /api/settings?project=` | `views.settings_view` (resolved values, the scope's overrides, the raw file) · `configure.save_settings` (`settings.set_values`, journaled) |
| `GET /api/workflows?project=` | `views.workflows_view`: workflows as written, the steps that would run, loop caps, each role's CLI |
| `GET /api/agents?project=&window=&refresh=` | `views.agents_view`: providers (detection, sign-in, slots, spend), the role roster, limits, routing |
| `GET /api/memory?project=` · `POST /api/memory/compact` · `GET /api/links` · `POST /api/links/repair\|relink\|adopt` | `views.memory_view` (files, caps, links, ticket index, memory writes) · `compaction.start_checked` · `views.links` · `projects.doctor(fix=True)`, `projects.relink`, `projects.adopt` |
| `POST /api/pause` · `POST /api/resume` | `controls.pause`, `controls.resume` |
| `GET /api/events` | journal tail as SSE |

## 4. Parity checklist (canvas → build)

Each canvas element is built, built differently because the system spec says otherwise, or left out because nothing in the system backs it. Closed on 2026-10-24: every "Built" item was checked against the running screens (headless captures at 1440, 1093 and 390 px beside the canvas boards, demo and empty stores). On 2026-10-23 the canvas itself (version 23) was reworded to folder links on the Settings, Memory, Ticket and Board boards, with the real store layout (`memory/`, `projects/<slug>/tasks/`), so the link rows below now match it.

| Screen | Built | Built differently | Left out |
|---|---|---|---|
| all | sidebar (Overview, Task board, Workflow, Agents, Memory, Settings) with counts (tickets, agents on/total, broken links); CLI pool; search (the top-bar box filters the board by id, title, tag or project); `/to-ticket` and `/to-loop` hints | "loop engine running" → live conductors (system spec §9) | — |
| Overview | stat tiles, live sessions table, approvals with Grant loops / Park, token spend, journal tail with follow; window Today · 7 days · All; Pause all | "PLAN STALLED: read both plans" → links to the ticket's plan and Findings | "avg skill read" (not measured) |
| Task board | board top bar (project, importance and agent filters, filter, Board · List, `/to-loop`), columns per step with counts and footers, cards (importance, parallel or serial, loop dots, provider, diff size, findings, gate chip), group by status, project or importance, List view, importance legend | "wip cap" → the step's slot use; gated tickets stay in their step's column with a chip (decision 14) | "Add ticket" (tickets come from `/to-ticket`; the footer says so) |
| Ticket detail | sheet over the dimmed page with breadcrumb, header with actions, tabs Overview · Changes · Timeline · Memory file, changes table and per-file diff, findings cards, prompt, acceptance checkboxes, dependencies, step timeline, ticket file, memory writes, numbered agent chain, metadata, attach command, send back, force move | "Reveal hard link" → both paths of the ticket file: the store's and the repo's through its folder link; the prompt panel shows the whole plan on demand | — |
| Workflow editor | config top bar, per-importance tabs, top-to-bottom graph on a dotted canvas with icons, ports and labelled send-back edges, toolbar (add, dry run, zoom), selected step panel (agent, model, skill, on_fail target, max loops, diff-only, session reuse), node library, loop guard rails, save to SETTINGS.md | free node positions → automatic layout ("Auto-layout" always on); "Add node" → the library adds after the selected step; "Dry run" → shows the effective steps | "Drag from a port" (retarget from the panel instead) |
| Agents | scope tabs, providers with sign-in, slots, spend; roster with switches, CLI and model, skill, used in, tokens, row editor; limits; importance routing | "Sign in" → the command to run (harness never signs in for you), "Install" when the CLI is missing; "Manage session" → "Check sign-in again"; "Hold serial tickets until the module is free" → a note (the scheduler always does it) | "Kill the session when a ticket stalls over 30 minutes" (no such setting); "New agent" (roles are fixed by the workflow steps); the per-role "PARALLEL" column (limits are per provider) |
| Settings | config top bar with overrides count, loop limits, token discipline, project commands (`project.test_cmd`, `project.lint_cmd`), status flow, SETTINGS.md view with set-here highlighting, memory section (file cards, shared store tree, inside-the-project tree) with Re-link, Adopt and Compact now (decision 12) | "hard-linked" → "linked by one folder link" (system spec §4.2); "Park the ticket instead of asking" → the off state of "Ask me when a ticket hits its cap" (one setting); "Reuse one CLI session per provider" → per ticket and role (`sessions.reuse`); status flow read-only | "Prefer shell commands over prose in skills" (a skill-writing rule, not a setting); status flow "add" (sub-statuses follow the steps) |
| Memory | top bar (find, Verify links, Compact all), store stats, memory files table with a viewer, MEMORY.md with compact, link health per project with Repair, Re-link and Adopt, stores found nearby, ticket index with models, memory writes, backends card | "HARD LINKS n/m" → "FOLDER LINKS n/m"; "Adopt by hard link" → Adopt (`harness adopt`); backend "sqlite index", "vector recall" shown as planned; "READ COST" → MEMORY.md characters ÷ 4; "Verify links" → checks link health again | "Retention" options (no such settings); "Ignore" on a found store (no ignore list); MEMORY.md "History" |

## 5. Acceptance (SP5 exit)

- [x] `harness ui open` starts or reuses the server, prints the URL, opens the browser; `harness ui stop` ends it; without the extra it exits 4 naming the install command.
- [x] Requests without the token, with a foreign `Host`, or a `POST` without `X-Harness` are refused.
- [x] The seven screens render a seeded store in Chrome and update live over SSE.
- [x] Every UI action goes through `ops` (import-linter keeps `ui` off the store) and is journaled with `by: ui`.
- [x] Settings saves keep comments and untouched keys.
- [x] The parity checklist (§4) is complete; the `open-ui` eval passes on claude and agy.
