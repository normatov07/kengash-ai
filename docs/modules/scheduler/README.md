# scheduler

## Purpose

Pick which ready tickets may start now (SP3 spec §7): no `touches` overlap inside a project, a free provider slot on the machine and in the project, and fair turns between projects. Pure: tickets, running work and limits in, a selection out.

## Interface

- `overlaps(a, b)`: path prefixes overlap when one contains the other segment by segment; an empty list is the whole repo.
- `fits(provider, project, used, machine, projects)`: one more session stays within the machine's and the project's limits.
- `select(candidates, busy, held, machine, projects, last_claims)` → `Selection(chosen, held_back)`; `held_back` maps a ticket id to `touches overlap <id>` or `no free <provider> slot`.
- Types: `Candidate(id, project, importance, created, touches, provider)` (`provider` None: the step needs no slot), `Busy(id, project, touches)`, `Held(project, provider)`, `Limits(total, per_provider)`.

## Invariants

- Imports only `model`; no I/O and no clock.
- Turn order: projects by oldest last claim (never claimed first, then by slug); inside a project critical, standard, simple, then oldest, then id.
- A chosen ticket holds its paths and its slot for the rest of the walk, so one selection never holds two overlapping tickets of a project or more sessions than the limits allow.

## Changes

- 2026-11-07: `Candidate.editing` (its start step is in the editing phase: only then do paths matter, and only then does a chosen candidate hold its paths) and `Candidate.weight`; `chain_weights(depends)`: each ticket's longest chain of waiting dependents (a cycle counts as none); inside a project the longest chain goes first, then importance, then age (SP16).
- 2026-10-26: the package is `kengash_ai` (the app is Kengash AI, distributed as `kengash-ai`; SP7 spec decision 16).
- 2026-10-23: `fits` is public; `ops.slots` uses it (SP3 M3).
- 2026-10-22: overlap, slots, project turns (SP3 M1).
