# ops

## Purpose

Use cases shared by the CLI and the UI. Each function takes plain arguments, works through `store`, `model` and the `settings`, `memory` and `journal` units, and returns a dataclass the caller formats.

## Interface

- `projects.init_project(path)` → `InitResult`: registers the repo containing `path`, seeds its store folder, links `<repo>/.harness`, adds the exclude entry. Idempotent.
- `projects.relink(slug, new_path)` → `InitResult`: re-points a moved project.
- `projects.doctor(fix, scan)` → `DoctorReport`: one `Problem` per repo, link, exclude or document issue, then repo trust and provider checks; `fix` repairs links and exclude entries only. `Problem.warning` marks findings that never fail `doctor`.
- `slots`: `queue_slot` (a claim queues its first slot), `acquire` (a worker's waiter is granted once every earlier waiter that fits has been), `release`, `occupied` (held plus queued, for claims), `limits` (defaults scope and each project), all under `slots.lock`.
- `steps.run_job(ticket_id, project=, steps=)` → `JobEnd(status, reason)`: the step loop of SP3 spec §5. Per step: flags and caps under the project lock (`workflow.before`), the agent (`agents.pick`), a slot (`waiting_slot` while queued), the session (reused per role and provider; claude ids chosen before the call), the prompt, one adapter call, a commit with trailers after editing steps (agent commits folded by `reset --soft`), then Handoff or Findings, Log, tokens, session, `step.end`, routing (`workflow.after`) and a store commit under the lock. `steps=N` pauses after N steps. Errors: `timeout` retries once; `schema` gets one repair turn on the session; `rate_limit` falls back (`fallback_on_rate_limit`) or waits as `waiting_quota` until `retry_after` (15 minutes when unknown); `auth` fails with "sign in to <cli> interactively"; others fail with the log path. A failing commit hook gets one repair turn. A ticket the user moves mid-step keeps its status; the result is dropped. A dead worker's `running` call gives its session back (`recover_session`). `steps.fail_ticket(paths, slug, id, reason)` fails a running ticket; `heartbeat`, `forget_worker` and `fail_job` serve the worker.
- `controls.run_tickets(ids, steps=, project=, by=)` → `RunResult(started, skipped)`: under the project lock, a live worker, the status (`in_queue/ready` or `in_process/failed|stalled|paused`), a pause, `touches` overlap, the first step, the agent (`NeedsSetup` when nothing usable) and a slot (`slots.reserve`) are checked; a claim creates or reuses the worktree (under `repo-<slug>.lock`), sets step and status, starts `python -m super_harness.worker` (`spawn_worker`) and writes its record. An approve step waits for `harness approve` without a worker. A network-less codex sandbox → `NeedsSetup`.
- `controls.approve_ticket`, `park_ticket` (deferred while a worker runs), `stop_ticket` (SIGTERM, SIGKILL after 10 s, then failed "stopped"), `pause`, `resume`.
- `lifecycle`: `step_status` (the `status.names` sub-status), `status_event` (the journal event of a status, with `status`, `loop`, `loop_max`, `reason`), `progress_for` and `apply_progress` (workflow progress to and from a ticket and its state), `pid_alive`, `DEAD_AFTER_S`.
- `slots.reserve`: a claim's check and queueing under one lock.
- `tickets.refresh_queue` (was private): turn queued tickets ready or blocked to match their dependencies.
- `prompts`: step instructions, `new_prompt` (role, step, Goal, Scope, Acceptance, Handoff, Findings, diff stat inline), `resumed_prompt` (Findings for work steps; Handoff and diff stat for review steps), `repair_prompt`, `handoff_text` (redacted, 15 lines), `findings_text`, `log_line`, `output_kind`, `profile`, `role_skill` (project `roles/`, then `defaults/roles/`).
- `agents.pick(settings, role, status, skip=)` → `Pick(role, provider, model, fallback)`: the role's `cli`, then each fallback, first usable; `NeedsSetup` naming the install or sign-in step when none is. `agents.detector(paths)` detects each provider once.
- `providers.check_providers(paths)` → `ProviderCheck(provider, users, blocking, message)` for each provider that enabled agents, their fallbacks or the compactor need (all scopes) and that is missing, signed out or unsupported (`blocking` when a role or the compactor is left with no usable provider), plus a warning for a claude login other than claude.ai unless `providers.claude.allow_api_key`; scopes with invalid settings are skipped. Detection goes through `adapters`.
- `providers.trust_notice(paths, slug, repo)`: a warning when the repo ships `.claude/settings.json` hooks or `.mcp.json`, once until those files change (digest in `runtime/trust.json`).
- `projects.adopt(path)` → `AdoptResult`: merges a real `.harness/` folder by uuid and archives the original.
- `workspace`: `resolve_slug` (the named project, else the registered project containing the current folder), settings `settings_yaml`/`setting`/`settings_problems`, memory `remember`/`recall`, `context` → `Context(memory, project, process, gates)` (MEMORY.md, PROCESS.md headings, open gates) and `open_gates` → `OpenGate(id, sub_status, title)` items.
- `records`: `scope`, `locate_plan`, `locate_ticket` (ids are store-unique; `project` narrows the search), `taken_ids`, `project_tickets`, `load_plan`/`load_ticket` (schema errors become `UserError`), `document` → `Document(project, path, meta, sections, text)`, `describe` (one line per validation error, with a "did you mean" for unknown fields and a quoting hint for YAML text read as a mapping), `one_line`, `record` (journal the events, then commit).
- `plans`: `new_plan`, `save_plan`, `show_plan`, `approve_plan`, `reject_plan` → `PlanResult(id, project, status, sections, review_skipped)`; approval needs a review verdict, a quick plan, `plan.review_max: 0`, or `skip_review`.
- `tickets`: `add_tickets` → `Batch(plan, project, tickets=[NewTicket(id, key, title, status)])`, `show_ticket` → `Document`, `list_tickets`/`find_tickets` → `TicketLine(id, project, status, importance, title)`; without a project they cover the project here, else every project.
- `tickets.move_ticket` → `Moved(id, project, before, after, ready, blocked)`; `tickets.set_fields` → `Updated(id, project, fields, status)` for the `SETTABLE` fields.
- `status.board(project=None)` → `Board([ProjectStatus(project, folders, statuses, gates)])`: every registered project unless one is named.
- `queue.next_tickets(project=None)` → `Queue(runnable, held_back, blocked, running, gates, paused)`: `runnable` holds `NextTicket(id, project, importance, step, provider, title)` in start order (`provider` is `shell` or `user` when the step needs no session); `held_back` maps each waiting ready ticket to its reason. `queue.progress_of(settings, ticket)` → `workflow.Progress`.
- Errors are `model` errors and carry their exit code.

## Invariants

- Registry changes happen under `runtime/locks/registry.lock`; project, plan and ticket changes under `runtime/locks/<slug>.lock`, then journal events, then a store commit.
- Every state change ends with a store commit (`harness: <command> <slug>`).
- Adopt deletes nothing: the original folder and every losing copy end up in `projects/<slug>/archive/adopted-<stamp>/`.
- `ticket add` validates the whole batch (schema, keys, references, cycles, workflows) before writing any ticket; a ticket is `ready` only when every dependency is merged or closed (`done/branch_ready` keeps dependents blocked).
- Queued tickets stay consistent: after any move or `depends_on` change each `ready`/`blocked` ticket is re-derived from its dependencies; `parked` is left alone; `in_process` needs every dependency merged or closed; a move to `done` clears the ticket's `step`, while parked or requeued tickets keep it and resume there.
- `ops` never imports `cli` or `ui`.

## Changes

- 2026-10-23: worker wrappers in `steps` (SP3 M3).
- 2026-10-23: `controls`: run, approve, park, stop, pause, resume; `slots.reserve` (SP3 M3).
- 2026-10-23: step retries, fallbacks, quota waits, hook repair, user moves, session recovery (SP3 M3).
- 2026-10-23: `steps` step loop, `lifecycle`; `tickets.refresh_queue` is public (SP3 M3).
- 2026-10-23: `prompts` and `agents` (SP3 M3).
- 2026-10-23: `slots`: queued and held provider slots (SP3 M3).
- 2026-10-23: doctor checks providers and repo trust (SP3 M2).
- 2026-10-22: `queue.next_tickets` (SP3 M1).
- 2026-10-22: dependencies are met only by `done/merged` and `done/closed`; a move to `done` clears `step` (SP3 M1).
- 2026-10-22: `describe` hints at quoting YAML text that contains `: ` (SP2 review).
- 2026-10-22: board status (SP2 M3).
- 2026-10-22: ticket move and set (SP2 M3).
- 2026-10-22: `tickets` add, show, list, find (SP2 M3).
- 2026-10-22: `records` and `plans` (SP2 M3).
- 2026-10-22: `context` returns a `Context` dataclass instead of text (SP2 M2 review).
- 2026-10-22: workspace use cases for settings, memory and context (SP2 M2).
- 2026-10-22: `relink` refuses a path already registered under another slug.
- 2026-10-22: project use cases: init, relink, doctor, adopt (SP2 M1).
