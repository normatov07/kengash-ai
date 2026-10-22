# model

## Purpose

Pydantic schemas and error types that every other unit shares. No I/O and no imports from other harness units.

## Interface

- `Plan`, `Ticket`, `Review`, `SessionRef`, `PlanMode`, `PlanStatus`: frontmatter schemas (system spec §4.4). Unknown keys are rejected and assignments are validated.
- `Doc[M]`: a frontmatter model plus ordered Markdown sections; `PLAN_SECTIONS` and `TICKET_SECTIONS` name them.
- `Registry`, `ProjectEntry`: `registry.yaml`.
- `Importance`, `Gate`, `Folder`, `ShortId`, `Title`, `utc_now()`.
- `TicketInput`: one item of `harness ticket add` input (SP2 spec §4); unknown fields are rejected.
- `SUB_STATUSES`: sub-statuses per folder (`in_process` also takes the step names of `status.names`); `Ticket.sub_status`.
- `Settings`, `Agent`, `Workflow`, `STEP_ROLES`: the SETTINGS.md schema; workflows may only use known steps whose agents exist.
- `Event`: journal event with core fields `ts` (converted to UTC; naive times count as UTC), `type`, `project`, `ticket`, `plan` plus any extra detail.
- Errors carry exit codes: `HarnessError` and `UserError` 1, `NeedsSetup` 4, `NeedsUser` 5.

## Invariants

- `Ticket.status` is `<in_queue|in_process|done>/<sub_status>`; `Ticket.folder` derives from it.
- Short ids are 8 lowercase hex digits: the first 8 of a uuid4.
- Timestamps are UTC at second precision.
- Plan and ticket titles are one trimmed, non-empty line.

## Changes

- 2026-10-22: `TicketInput`, `SUB_STATUSES`, one-line `Title`, `Ticket.sub_status` (SP2 M3).
- 2026-10-22: provider slot counts must be ≥ 0; event times are kept in UTC (SP2 M2).
- 2026-10-22: `Settings` and `Event` schemas (SP2 M2).
- 2026-10-22: plan, ticket and registry schemas, error types (SP2 M1).
