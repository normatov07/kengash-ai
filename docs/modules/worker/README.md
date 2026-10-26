# worker

## Purpose

Run one detached job (SP3 spec §3, decision 1): `harness run` starts `python -m kengash_ai.worker ticket <id> [--steps N] [--project SLUG]` in its own session, logging to `runtime/logs/<id>.log`. The worker is a frontend, as `cli` is for commands: the job itself is `ops.steps.run_job`.

## Interface

- `ticket <id>`: run the ticket's steps until a gate, the end, a pause or park request, or `--steps N` steps; print `<id>: <status>: <reason>`; exit 0.
- `plan-review <id>`: one review round of an `in_review` plan (`ops.reviews.run_review`); print `<id>: round <r> <verdict>` or `<id>: review ended: <reason>`; exit 0. An unexpected error journals `worker.exited` (`ops.reviews.fail_review`) and exits 1.
- `compact`: compact MEMORY.md (`ops.compaction.run_compaction`, worker id `compact`); print the line counts or why the result was kept out; exit 0.
- A daemon thread calls `ops.jobs.heartbeat` every 15 s (`HEARTBEAT_S`); the dead-worker check treats a heartbeat older than 2 minutes as dead.
- SIGTERM (`harness stop`) raises `SystemExit(143)`; the adapter's process runner ends the running CLI's process group on the way out. `stop` then marks the ticket failed "stopped".
- An unexpected exception prints its traceback to the log, fails the ticket with `worker error: <message>; log: runtime/logs/<id>.log`, and exits 1.
- On exit the worker drops its own record (`ops.jobs.forget`), never a newer worker's.

## Invariants

- Imports only `ops` and `model` (import-linter); never the store directly.
- `ops` never imports `worker`; it starts it as a process.
- The worker never writes a stopped state (SP3 spec decision 22).

## Changes

- 2026-10-26: the package is `kengash_ai` (the app is Kengash AI, distributed as `kengash-ai`; SP7 spec decision 16).
- 2026-10-23: `plan-review` and `compact` jobs (SP3 M4).
- 2026-10-23: heartbeat and record cleanup moved to `ops.jobs` (SP3 M4).
- 2026-10-23: ticket jobs with heartbeat and clean stop (SP3 M3).
