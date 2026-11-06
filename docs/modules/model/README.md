# model

## Purpose

Pydantic schemas and error types that every other unit shares. No I/O and no imports from other kengash units.

## Interface

- `Plan`, `Ticket`, `Review`, `SessionRef`, `PlanMode`, `PlanStatus`: frontmatter schemas (system spec §4.4). Unknown keys are rejected and assignments are validated. `Ticket.step` is the step running or next, `Ticket.tokens_max` the token budget (empty: `tokens.per_ticket_max`), `Review.session` the plan reviewer's session.
- `Doc[M]`: a frontmatter model plus ordered Markdown sections; `PLAN_SECTIONS` and `TICKET_SECTIONS` name them.
- `Registry`, `ProjectEntry`: `registry.yaml`.
- `SlotEntry`, `SlotTable`, `Claims`, `Trust`: `runtime/slots.json`, `runtime/claims.json` and `runtime/trust.json` (SP3 spec §4).
- `WorkerRecord` (`runtime/workers/<id>.json`; `job`: `ticket`, `plan-review` or `compact`), `TicketState` with `Running` (`runtime/tickets/<id>.json`: stall streaks, plan-review rounds, pending approval, editing start commit, agy usage totals, the call in flight, call count), `ConductorPing` and `JournalCursor` (`runtime/conductors/`), `LoopLease` (`runtime/loops/<pid>.json`: pid, agent, process name, project or None for every project, started, seen; SP11).
- `Importance`, `Gate`, `Folder`, `ShortId`, `Title`, `utc_now()`.
- `TicketInput`: one item of `kengash ticket add` input (SP2 spec §4); unknown fields are rejected.
- `SUB_STATUSES`: sub-statuses per folder, `in_process/paused` included (`in_process` also takes the step names of `status.names`); `Ticket.sub_status`.
- `Settings`, `Agent`, `Workflow`, `CustomStep`, `ProviderOptions`, `STEP_ROLES`, `BUILTIN_KINDS`, `PROVIDERS`, `split_cli`: the SETTINGS.md schema; `steps.<name>: {role, kind, does}` adds a custom step (SP6: kind `read`, `edit` or `review`; not a built-in name; its role an agent on a model CLI (not `shell`) whose name follows the skill-name rule (`ROLE_NAME`: lowercase words joined by single hyphens, 2 to 31 characters); `does` one line ≤ 200 characters; only a custom review step may have an `on_fail` edge); `Settings.role_of(step)`, `kind_of(step)` (`Kind`: built-ins included, `run_tests` is `check`) and `step_names()` answer for built-in and custom steps alike; workflows may only use those steps, and their agents must exist; an agent's `cli` names a provider or `shell`, while fallbacks and `memory.compactor` name a provider, and `plan.reviewer` names one or is `different-provider`; `Settings.provider(name)` gives a provider's worker options, defaults included. SP10: `BUILTIN_SKILLS` fixes each built-in role's skill; `routing` maps an importance (`IMPORTANCES`) to an existing workflow and `Settings.workflow_for(importance)` falls back to the workflow of that name; workflow names match `WORKFLOW_NAME`, a workflow holds each step once, `on_fail` only sends back to an earlier step; a `provider/model` value needs a one-word model of at most 100 characters.
- Step contract (SP3 spec §8): `StepRequest` (role, worktree, prompt, output kind, permission profile, timeout, raw-output log, model, session and resume, skill text, test and lint commands, provider options, the session's previous usage totals), `StepResult` (session, parsed output, text, usage, totals, duration, `error` kind, `retry_after`, detail; `ok` when `error` is None), `Usage` (`tokens` = input + output; `minus` subtracts running totals), outputs `WorkOutput`, `ReviewOutput` (a fail needs findings), `CompactOutput`, `Finding`, their strict `OUTPUT_SCHEMAS` and `parse_output`; `ProviderStatus` (installed, version, signed in, auth method, hint; `usable`).
- `Event`: journal event with core fields `ts` (converted to UTC; naive times count as UTC), `type`, `project`, `ticket`, `plan` plus any extra detail.
- Errors carry exit codes: `KengashError` and `UserError` 1, `WaitTimeout` 3, `NeedsSetup` 4, `NeedsUser` 5, `LoopBusy` 6 (SP11).

## Invariants

- `Ticket.status` is `<in_queue|in_process|done>/<sub_status>`; `Ticket.folder` derives from it.
- Short ids are 8 lowercase hex digits: the first 8 of a uuid4.
- Timestamps are UTC at second precision.
- Plan and ticket titles are one trimmed, non-empty line.

## Changes

- 2026-11-06: `Settings.fallback_on_error` replaces `fallback_on_rate_limit` (SP12 M1).
- 2026-11-06: `ErrorKind` gains `network`; `StepResult.warning` keeps an error a CLI reported after a valid output (SP12 M1).
- 2026-11-06: `LoopLease`, `LoopBusy`; `Settings.loop_start: ask | auto` (SP11 M1).
- 2026-10-30: `ProviderStatus.models` (SP10 M3).
- 2026-10-30: fixed built-in skills (`BUILTIN_SKILLS`), `routing` and `workflow_for`, workflow name and duplicate-step rules, send-back-only edges, one-word models (SP10 M2).
- 2026-10-26: the base error is `KengashError` (was `HarnessError`); user-facing text names `kengash` (SP8).
- 2026-10-26: the package is `kengash_ai` (the app is Kengash AI, distributed as `kengash-ai`; SP7 spec decision 16).
- 2026-10-26: `PROVIDERS` is claude, codex, antigravity; `REPLACED`/`replaced()` turn any `gemini` in agents, fallbacks, compactor, plan reviewer or `providers` into "gemini is replaced by antigravity …"; a legacy `sessions.per_provider.gemini` is dropped on load (SP7).
- 2026-10-26: `Logs` (`logs.keep_days`, default 30, 0 keeps all) (SP7).
- 2026-10-26: the provider check's keyword is `allow_shell` (ruff's security rules read `shell=True` as a subprocess call) (SP7).
- 2026-10-26: custom steps: `CustomStep`, `Settings.steps`, `role_of`, `kind_of`, `step_names`, `BUILTIN_KINDS` (SP6).
- 2026-10-23: `UiRecord` (SP5 M1).
- 2026-10-24: `Expect.ui` (SP5 M3).
- 2026-10-23: `Expect.clean` (SP4 M3).
- 2026-10-23: eval scenarios: `EvalScenario`, `SetupStep`, `Expect`, `RecordsExpect` (SP4 M2).
- 2026-10-23: `SkillMeta`, skill frontmatter (SP4 M1).
- 2026-10-23: `plan.reviewer` is validated (SP3 M4).
- 2026-10-23: `WorkerRecord.job` names plan-review and compaction jobs (SP3 M4).
- 2026-10-23: `WaitTimeout` (exit 3) (SP3 M4).
- 2026-10-23: `WaitTimeout` (exit 3) (SP3 M4).
- 2026-10-23: worker, ticket-state, conductor and cursor runtime models (SP3 M3).
- 2026-10-23: `Trust` runtime file (SP3 M2).
- 2026-10-23: step contract and provider status (SP3 M2).
- 2026-10-22: runtime file schemas (SP3 M1).
- 2026-10-22: provider names checked, `ProviderOptions`, `memory.compactor`, `bypass_permissions`, ticket `step` and `tokens_max`, `paused`, `Review.session` (SP3 M1).
- 2026-10-22: `TicketInput`, `SUB_STATUSES`, one-line `Title`, `Ticket.sub_status` (SP2 M3).
- 2026-10-22: provider slot counts must be ≥ 0; event times are kept in UTC (SP2 M2).
- 2026-10-22: `Settings` and `Event` schemas (SP2 M2).
- 2026-10-22: plan, ticket and registry schemas, error types (SP2 M1).
