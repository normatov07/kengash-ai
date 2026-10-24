# SP5 UI Parity: Match the Claude Design Canvas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** every screen looks and behaves like its board on the canvas `https://claude.ai/artifact/JiMGMkbaw8qhafeaNbqU7d`, driven by real store data, with no layout defects at 1440 px, 1093 px or phone width.

**Architecture:** The canvas boards are static HTML with inline styles. Each screen is rebuilt by porting its board's markup region by region into `ui/static/views/<screen>.js` templates and `app.css` classes that carry the board's exact values (colour, size, radius, spacing), then binding the regions to `/api` data. The shell gains two per-screen slots, a top bar and a sidebar footer card, because every board has its own. Read models grow only where a board shows data the API lacks.

**Tech Stack:** as M2; Inter and JetBrains Mono bundled as woff2 (OFL-1.1); headless Chrome over CDP for screenshot comparison (`scratchpad/tools/cdp-shot.mjs`, canvas boards made standalone by `scratchpad/tools/standalone.py`).

**Spec:** `docs/superpowers/specs/2026-10-23-sp5-ui-design.md` (decisions 1, 8, 10, 12; §4) and the canvas boards `project/Main|Board|Ticket|Workflow|Agents|Settings|Memory.dc.html` (1440 px wide; heights in `project/canvas.json`).

## Global Constraints

- The canvas wins on look; the system spec wins on behaviour. A canvas control with nothing behind it stays out and is listed in spec §4; one the system backs differently is built that way and listed.
- Tokens are the canvas's: background `#0E1012`, sidebar and panels `#16191D`, cards `#1A1E22`, raised `#1C2026`, borders `#262B32` and `#1F242A`, input borders `#323943`, text `#ECEFF3`, muted `#A7B0BC`, faint `#78828F`, dim `#5A646F`, accent `#F0883E` (hover `#FFA463`), ok `#5FC08B`, danger `#EF7A72`, warn `#D8B24C`, info `#68A4E0`, review `#B191E8`; radii 7 px (controls), 11–12 px (panels), 20 px (pills); type sizes 9–15 px, headings 24 px, tile values 32 px.
- Step colours everywhere (sessions, board columns, journal kinds, graph nodes): plan `#68A4E0`, review_plan and review_code `#B191E8`, implement `#F0883E`, security `#D8B24C`, run_tests and docs `#5FC08B`, done `#5FC08B`, approve `#EF7A72`.
- No network at runtime; every value escaped; keyboard focus visible; `prefers-reduced-motion` respected; module docs change with modules; commits end with the Co-Authored-By line.
- Each screen task ends with a screenshot pass: our screen and its board side by side at 1440 px from the demo store, every difference fixed or ruled on in the ledger, then a 1093 px and a 390 px pass for overflow.

## Review Focus

1. Long values (absolute paths, long titles, many models) never break a layout: they truncate with the full value in `title` (all tasks).
2. A slow call (provider detection, a large diff) never blanks a screen or leaves the nav pointing at the old route (Tasks 2, 7).
3. An empty store renders every board region with an empty state that says what to do, not a broken grid (all tasks).
4. Tickets at a gate stay findable on the board: in their step's column with the gate's chip (Task 4).
5. Unsaved edits on a configure screen survive live refreshes and are lost only on Discard or navigation (Tasks 6–8).

---

### Task 1: Spec decisions for parity
- [ ] Edit the SP5 spec: decision 1 (Inter and JetBrains Mono ship as woff2 under OFL-1.1, still nothing fetched), decision 10 (top-to-bottom layout like the canvas, with zoom), new decision 14 (each screen has its own top bar and sidebar footer card; the ticket opens as a sheet over a dimmed page; tickets at a gate stay in their step's column), and refresh §4 for the items below. Commit `docs: SP5 canvas parity decisions`.

### Task 2: Foundation: fonts, tokens, components, shell slots
**Files:** Create `ui/static/fonts/` (Inter and JetBrains Mono latin woff2 + `OFL.txt`), `ui/static/icons.js`; Modify `app.css`, `app.js`, `index.html`, `views/*.js` (move each top bar into its view), `ops/views.py` (`Overview.tickets_total`, `Overview.agents_on`, `Overview.agents_total`), `pyproject.toml` (fonts in the wheel); Test `tests/test_ui_static.py`, `tests/test_ops_views.py`.
**Interfaces:** each screen module may export `top(data, app)` and `foot(data, app)` (html templates); `app.js` mounts them into `#top` and the sidebar footer, falling back to the default top bar (project select, search, `/to-ticket`, `/to-loop`) and no footer. `icons.js` exports `icon(name, size)` with the canvas's SVG paths (nav set, plus-square, play, warning, trash, pencil, link, link-broken, folder, check, close, chevron, step icons: trigger, plan, review, implement, security, tests, approve, done). Components in `app.css`: `.select` (native select, canvas chevron), `.switch` (toggle), `.tabs-line` (underline tabs), `.badge`, `.pill`, `.chip`, dark scrollbars.
- [ ] Tests: fonts served with `font/woff2`; `@font-face` present in `app.css`; overview counts tickets and enabled agents. Nav highlight moves on `hashchange` before data loads. Screenshot pass of the shell. Commit `feat(ui): canvas tokens, bundled fonts, icons and shell slots`.

### Task 3: Overview
**Files:** `views/overview.js`, `app.css`, `ops/views.py` (`Overview.avg_loops_done`, `Overview.avg_ticket_cost`, `Session.pid` absent → no stop button), `tests/test_ops_views.py`.
- [ ] Port Main.dc.html: tiles (Done today note "avg N loops to done"), live sessions table with step colours and a stop button per row (`POST stop`, second click), the panel stretching to the right column, approvals with the warning icon and gate badges (LOOP CAP, PLAN STALLED, FAILED, READY TO MERGE) and a sentence per gate, token spend with "avg ticket cost", loop journal under both with humanised lines (`impl 4f2a1b7c codex wrote 3 files +128 −14 loop 2/6`) coloured by kind and Follow tail; CLI pool as the sidebar footer card. Tests for the two averages. Screenshot pass. Commit `feat(ui): overview matches the canvas`.

### Task 4: Task board
**Files:** `views/board.js`, `app.css`, `ops/views.py` (columns: in queue, each step any workflow uses, then done; a ticket at a gate or waiting stays in its step's column with `Card.chip` = loop cap hit, stalled, failed, waiting slot, waiting quota, paused, ready to merge; tickets with no step go to in queue or done; `Card.rejected` = failed `review_plan` steps; `Column.footer` = the step role's live sessions, or for implement its provider's slot use), `tests/test_ops_views.py`.
- [ ] Port Board.dc.html: board top bar (project, importance and agent filters, filter input, Board · List toggle, `/to-loop`), title with running · blocked · done today, Group by (status, project, importance), full-height columns of fixed width with coloured top edge, count, footer, cards (importance badge, parallel or serial, loop dots, title, provider chip, findings or chip, diff, id and project), "Blocking gate" placeholder on an empty gate column, a List view (sortable table), the importance legend as the sidebar footer. Tests for gate placement, chips and footers. Screenshot pass. Commit `feat(ui): task board matches the canvas`.

### Task 5: Ticket sheet
**Files:** `views/ticket.js`, `app.css`.
- [ ] Port Ticket.dc.html: breadcrumb top bar, a sheet over the dimmed page closing to where the user came from (× and Escape), header (badges, uuid, title, meta line, loop pill, gate action), underline tabs Overview · Changes · Timeline · Memory file. Overview: prompt as a quote, cut-from line, acceptance as checkboxes (`- [x]` checked), dependency rows (BLOCKS, WAITS ON, SERIAL or PARALLEL). Changes: totals, files table, one diff panel per file chosen by row (split the ticket diff on `diff --git`), findings as cards parsed from `severity · file:line · issue · fix`. Timeline rows. Memory file: both paths, the file, memory writes. Rail: numbered agent chain, metadata, tags, stacked actions. Screenshot pass per tab. Commit `feat(ui): ticket sheet matches the canvas`.

### Task 6: Workflow editor
**Files:** `graph.js`, `views/workflow.js`, `app.css`, `tests/test_ui_static.py`.
- [ ] Port Workflow.dc.html: config top bar (scope select, "inherits defaults unless overridden", Discard, Save), title with importance tabs, canvas panel on a dotted grid with toolbar (Add node → library, Auto-layout, Dry run, zoom − % + fit), vertical layout with icons, ports and labelled send-back edges routed to the right, a "Run tests off" ghost node when the step is not in the workflow, legend; selected-step panel (icon, remove, agent, CLI · model select, skill (`agents.<role>.skill`), send-back target, max loops, diff-only and session-reuse checkboxes); node library with icons; loop guard rails as rows. Update the layout test to rows. Screenshot pass. Commit `feat(ui): workflow editor matches the canvas`.

### Task 7: Agents
**Files:** `views/agents.js`, `app.css`, `ops/views.py` (`agents_view(detect=False)` returns cached statuses or `checking`; `GET /api/agents/detect` runs detection), `ui/app.py`, tests.
- [ ] Port Agents.dc.html: scope tabs in the top bar, provider cards (signed in, signed out, not installed, rate limited when the slot table says so, not supported), Sign in / Install copy the command, roster with switches, CLI · model, skill, used in with importance bars, tokens, a pencil opening a row editor (CLI, skill, fallback, blocking), limits, importance routing rows. Detection loads after the page renders. Tests for the cached path. Screenshot pass. Commit `feat(ui): agents screen matches the canvas`.

### Task 8: Settings
**Files:** `views/settings.js`, `app.css`, `ops/views.py` (`MemoryView.projects`: per project ticket counts per folder), tests.
- [ ] Port Settings.dc.html: config top bar (scope select, overrides badge, Reset, Save), loop limits, token discipline, project commands, status flow, SETTINGS.md with YAML colouring and overrides in amber; Memory section: file cards (MEMORY.md, PROCESS.md, DECISIONS.md, AGENTS.md), Shared store tree with counts, Inside the project tree, Re-link · Adopt a found store · Compact now. Screenshot pass. Commit `feat(ui): settings screen matches the canvas`.

### Task 9: Memory store
**Files:** `views/memory.js`, `app.css`, `ops/views.py` (`MemoryFile.text`, last compaction before/after), tests.
- [ ] Port Memory.dc.html: top bar (store path, find, Verify links, Compact all), tiles, files table with the chosen file in the viewer below (MEMORY.md first), viewer footer (lines / cap, linked projects, last pass), link health as a compact list with a card per broken link and its fix, store found nearby card, ticket index with model chips, writes to memory full width, backend card as the sidebar footer. Screenshot pass. Commit `feat(ui): memory screen matches the canvas`.

### Task 10: QA and docs
- [ ] Every screen at 1440, 1093 and 390 px, empty store and demo store; keyboard walk (tab order, focus ring, Escape); fix findings. Module docs, architecture, AGENTS.md; `make check`; review the diff against this plan's Review Focus. Commit `docs: SP5 canvas parity`.
