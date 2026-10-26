# Memory and state files

Formats of the files in the `~/.kengash` store. They are the contract sub-project 2 implements; agents use them through `kengash` commands, never by editing them directly.

## Files

| File | Scope | Read by | Written by | Cap |
|---|---|---|---|---|
| `MEMORY.md` | global | the conductor at the start of every command (`kengash context`); workers get a digest | `kengash memory add` | 200 lines |
| `DECISIONS.md` | global; entries tagged `[project]` | planner, plan reviewer, conductor | `kengash memory add --decision` | 300 lines, then the oldest move to `memory/archive/` |
| `PROCESS.md` | project | workers of that project | user, conductor | 100 lines |
| `SETTINGS.md` | project | `kengash` only | user, UI | schema-validated |
| ticket `## Handoff` | ticket | the next worker | `kengash`, from worker JSON | 15 lines |

## Line formats

One fact per line, about 20 words at most.

```
MEMORY.md     sections: ## Working style · ## Goals · ## Preferences · ## Turned down
              - ships small, reviews hard; wants the diff, not prose
DECISIONS.md  - 2026-10-22 [payments-api] keyring over single secret, 48h overlap. why: zero-downtime rotation. rejected: one env var
```

## Writing and compaction

- Write only through `kengash memory add`; the journal records who wrote each line and why.
- Mark a line `(pin)` to keep it through compaction.
- When a file passes its cap, a one-shot worker on the cheapest configured model merges duplicates and drops stale lines. `kengash` accepts the result only if it is under the cap and keeps every pinned line. The previous version stays in the store's git history.

## SETTINGS.md

- The whole file is YAML; `#` lines are comments that read as Markdown headings.
- It is copied from `~/.kengash/defaults/SETTINGS.md` the first time a project is used, and never overwritten after that.
- `kengash` validates it and rejects unknown keys with a "did you mean" hint.
- Agents never parse it; they ask `kengash` for values.
- The full default file is in spec §4.6.

## PROCESS.md

Per project: how the project builds and tests, plus the process notes its workers need. At most 100 lines.

## Plans and tickets

Formats are in spec §4.4.

- One plan file per request (`plans/<id8>.md`) holds the user's prompt verbatim; tickets reference it by id and never copy it.
- One file per ticket (`tasks/<folder>/<id8>.md`) moves between `in_queue/`, `in_process/` and `done/` as its status changes.
- Agents never edit frontmatter; `kengash` writes it.
- `## Handoff` is replaced at every step; `## Log` gains one line per step.
