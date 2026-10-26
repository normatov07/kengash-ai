# SP6: Custom agents, CI and canvas follow-ups (design)

Date: 2026-10-26. Status: written under the user's instruction to continue without design questions (2026-10-26); the calls marked *call* are the builder's and open to veto.

## 1. Why

The original request asks for a UI that can "create new agent and change agent collaboration flow". SP5 left "New agent" out because roles were fixed by the eight built-in steps (`STEP_ROLES`). A requirements audit on 2026-10-26 also found every CI run red since the first push, and a canvas re-check found four small parity gaps. SP6 closes all three.

## 2. Goals, non-goals, anti-goals

- Goal: a user defines a new agent (a role, its CLI and model, its skill, what its step does) from the Agents screen or `harness agent new`, adds its step to any workflow, and tickets run it like a built-in step.
- Goal: CI green on Linux and macOS; the Foundation acceptance box for CI can be ticked.
- Goal: the four parity gaps of §6 closed.
- Non-goal: new engine behaviour. A custom step reuses one of the three behaviours the built-in steps already have.
- Non-goal: free-form graphs, parallel branches or conditional edges in a workflow.
- Anti-goal: a custom agent that can bypass the loop cap, the token cap, the blocking rule or the review verdict contract. Anti-goal: a custom agent that runs anything but an official CLI or `shell`.

## 3. Decisions

1. **Custom steps live in SETTINGS.md** as `steps.<name>: {role, kind, does}`. `name` matches `[a-z][a-z0-9_]{1,30}` and is not a built-in step (`plan`, `review_plan`, `implement`, `review_code`, `security`, `run_tests`, `docs`, `approve`). `role` names an agent in `agents`; `does` is one line (at most 200 characters) that becomes the step's instruction. Unknown keys are rejected like every other section.
2. **Three kinds, each an existing behaviour.** `read`: reads the code read-only and hands notes on (like `plan`). `edit`: edits the ticket's worktree; harness commits (like `implement`). `review`: reads the diff read-only and returns the review verdict with findings (like `review_code`); only a `review` step may have an `on_fail` edge, and it counts toward stall detection. Output schema, profile, diff stat and resumed prompts follow the kind.
3. **One lookup for every step.** `Settings.role_of(step)` and `Settings.kind_of(step)` answer for built-in and custom steps alike; engine, scheduler, views and the claim path stop indexing `STEP_ROLES` directly. Workflow validation moves to `Settings`: every workflow step is built-in or custom, every custom step's role exists, and an `on_fail` source is a review step.
4. **Status.** A custom step's sub-status is `status.names.<step>` when set, else the step name, as for built-ins today.
5. **Role skill.** `agents.<role>.skill` names a role skill as before. `harness agent new` writes a starter `roles/<skill>/SKILL.md` into the scope (`defaults/roles/` or `projects/<slug>/roles/`) unless one exists anywhere on the lookup path; the starter is per kind, within the skill caps, `metadata: {source: user}`, and the user may edit it. *call*: the skill is named after the role, and the step defaults to the role with `-` → `_`.
6. **CLI.** `harness agent new ROLE --kind read|edit|review --does TEXT [--cli PROVIDER[/MODEL]] [--step NAME] [--workflow NAME]... [--after STEP] [--send-back STEP] [--project SLUG] [--json]` adds the agent, its step, the step to each named workflow after `--after` (default: last before any `approve`), and for a review step the `on_fail` edge to `--send-back` (default `implement` when the workflow has it). `harness agent remove ROLE [--project SLUG]` removes a custom role, its steps, their workflow entries and `on_fail` edges, and keeps the skill file. Built-in roles cannot be removed (switch them off instead). Both journal `settings.changed` with `by` and commit the store.
7. **One ops entry point.** `ops.agent_config.new_agent` and `remove_agent` compute every key change, then write them through `settings.set_values` in one validated save (nothing is written when the result is invalid), then write the starter skill. The CLI and the UI call these and nothing else.
8. **UI.** Agents top bar gets the canvas's accent "New agent" button. It opens a sheet: role name, what it does, kind (three cards: Reviewer · Worker · Advisor), CLI · model, which workflows and after which step, and for a reviewer where a fail sends the ticket. Save posts `/api/agents` with `X-Harness`; the roster then lists the agent with a "custom" tag, and its row editor offers "Remove agent". Settings' status flow gets the canvas's "+ add", which opens the same sheet. The Workflow node library lists custom steps with their kind's icon, so they can be added to more workflows there. The board shows a column per custom step that a scope's workflows use, after the built-in step columns.
9. **Gemini is not built** (*call*). On 2026-06-18 Google moved Google AI Pro, Ultra and free users from Gemini CLI to Antigravity CLI, which harness already drives; Gemini CLI now serves Code Assist business licences and paid API keys only, and harness never uses API keys. `gemini` stays a known provider name; choosing it explains this and points to `antigravity`.

## 4. CI

Every run failed since the first push. Two tests depended on the dev machine: the help test read Rich output that GitHub's forced colours split with escape codes, and an eval test started its stand-in server with the Linux-only `setsid` command. Both fixed on 2026-10-26 (`fix(ci)`); the actions move to their Node 24 releases, pinned by commit.

## 5. Interfaces

- `POST /api/agents` body `{project, role, kind, does, cli, step?, workflows[], after?, send_back?}` → the saved keys; `POST /api/agents/{role}/remove` body `{project}`. Both refuse without `X-Harness`, like every POST.
- `GET /api/agents` roster rows gain `custom: bool` and `step: str|null`; `GET /api/workflows` gains `kinds: {step: kind}` and lists custom steps in `library` and `roles`; the board's columns include custom steps.

## 6. Canvas parity follow-ups

1. Board: with seven columns at 1440 px, three titles are cut ("PLAN REVI…"). Titles fit at 1440 px, and the column's "more" button no longer takes title space.
2. Board: the queue footer's "Add with /to-ticket" wraps under its icon; it stays on one line.
3. Workflow: the canvas numbers the end node ("6 · Done"); the build does too.
4. Agents: importance routing shows the loop cap where it differs from the simple workflow ("+ security, 6 loops").

## 7. Acceptance (SP6 exit)

- [x] `harness agent new perf-reviewer --kind review --does "…" --workflow critical --after review_code --send-back implement` adds the agent, the step, the workflow entry, the edge and a starter skill that passes `harness skills lint`; a ticket on `critical` runs the step with the fake CLIs, a fail sends it back and burns a loop (`test_new_agent_writes_one_valid_save_and_a_starter_skill`, `test_cli_agent_new_and_remove`, `test_a_custom_review_step_sends_the_ticket_back`, `test_a_custom_review_step_routes_like_review_code`).
- [x] An `edit` custom step's changes are committed under the ticket; a `read` step's notes reach the Handoff (`test_a_custom_edit_step_is_committed`, `test_a_custom_read_step_hands_notes_on`).
- [x] Invalid input (built-in name, unknown role, `on_fail` from a non-review step, unknown workflow) writes nothing and names the problem (`test_new_agent_refuses_without_writing`, `test_custom_step_problems`).
- [x] The Agents screen creates and removes a custom agent in Chrome; the board and Workflow editor show its step (headless Chrome on the demo store, 2026-10-26: add, duplicate refused in the dialog, Workflow node "5 · Perf reviewer", board column, `#/agents/new`, two-click remove).
- [x] §6 items checked by headless captures at 1440 px beside the canvas boards (no board title cut, footer on one line, "6 · Done", "+ security, 6 loops").
- [ ] CI green on ubuntu and macOS for 3.12 and 3.14.
- [x] `make check` green; module docs, architecture and the system spec updated (583 passed on 2026-10-26).
