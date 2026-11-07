# workflow

## Purpose

Decide what a ticket does next (SP3 spec §6): which steps its workflow runs, when a cap, a stall or an approval stops it, and where a failing review sends it. Pure: settings and progress in, decisions out.

## Interface

- `steps_for(settings, workflow, hitl=)`: the effective steps; roles that are off are skipped, `review_plan` is dropped at `plan.review_max: 0`, hitl tickets get `approve` after `plan`. `first_step(...)` is the first of them.
- `blocking_off(settings, workflow)`: a blocking role that is switched off.
- `before(settings, progress)` → `Routed`: run the step, or halt at the token cap or the approval step; a step whose role was switched off is skipped.
- `after(settings, progress, outcome)` → `Routed`: route a finished step; the first matching rule of SP3 spec §6 wins.
- `approve(settings, progress, approval, loops=, tokens=)` → `Routed`: what `kengash approve` grants; `blocked` runs an editing step again in the same loop and passes any other step (SP15).
- `Outcome.blocked`: a passing work step's `BLOCKED:` text; `after()` halts it at `needs_approval` with approval `blocked`, reason `blocked: <text>`, no loop added.
- `fingerprint(file, issue)`: 12 hex digits naming a finding across loops.
- Types: `Progress(workflow, hitl, step, loop, loop_max, tokens, tokens_max, streaks, plan_rounds)`, `Outcome(verdict, fingerprints)`, decisions `Run(step, loop)`, `Halt(status, reason, approval)`, `Merge()`, and `Routed(decision, progress)`.

## Invariants

- Imports only `model`; no I/O and no clock.
- `loop` grows only on a failing verdict with an `on_fail` edge, or when a loop cap is approved; a `review_plan` failure keeps it while `loop_count_rejected_review` is false.
- Stall streaks count consecutive failing runs of one review step (built-in or a custom step of kind `review`) per fingerprint; a pass clears that step's streaks.
- Roles and kinds come from `Settings.role_of`/`kind_of`, so custom steps (SP6) route exactly like the built-in step of their kind.
- `Halt.approval` is set exactly when `kengash approve` can open the gate.

## Changes

- 2026-11-07: `Outcome.blocked` halts a passing step for the user; `approve(…, "blocked")` (SP15).
- 2026-11-07: `Approval` gains `blocked` (SP15).
- 2026-11-06: the token-cap reason reads `token cap: <used:,> of <max:,> used; approve with --tokens N` (SP12 M1).
- 2026-10-26: the package is `kengash_ai` (the app is Kengash AI, distributed as `kengash-ai`; SP7 spec decision 16).
- 2026-10-26: steps are looked up through `Settings.role_of`/`kind_of`; custom review steps keep stall streaks (SP6).
- 2026-10-22: effective steps, caps, stalls, approvals, fingerprints (SP3 M1).
