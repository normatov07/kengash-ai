# Memory and state files

Formats of the files in the `~/.kengash` store. They are the contract sub-project 2 implements; agents use them through `kengash` commands, never by editing them directly.

## Files

| File | Scope | Read by | Written by | Cap |
|---|---|---|---|---|
| `MEMORY.md` | global | the conductor at the start of every command (`kengash context`); every new worker session (`## Memory`) | `kengash memory add` | 200 lines |
| `DECISIONS.md` | global; entries tagged `[project]` | the conductor; every new worker session | `kengash memory add --decision`; `plan approve` (`## Lasting decisions`); `merge` (the ticket's `## Decisions`); the harvest (SP18) | 300 lines, then the oldest move to `memory/archive/` |
| `PROCESS.md` | project | every new worker session of that project | user, conductor (`kengash memory add --process`) | 100 lines |
| `SETTINGS.md` | project | `kengash` only | user, UI | schema-validated |
| ticket `## Handoff` | ticket | the next worker | `kengash`, from worker JSON | 15 lines |
| ticket `## Decisions` | ticket | reviewers; DECISIONS.md once merged | `kengash`, from worker JSON | 6 lines |
| ticket `## Check output` | ticket | the implementer, the user | `kengash`, from a failing check's digest | 62 lines |

## Line formats

One fact per line, about 20 words at most.

```
MEMORY.md     sections: ## Working style · ## Goals · ## Preferences · ## Turned down
              - ships small, reviews hard; wants the diff, not prose
DECISIONS.md  - 2026-10-22 [payments-api] keyring over single secret, 48h overlap. why: zero-downtime rotation. rejected: one env var
              - 2026-11-09 [chess-samurai] (user) capture animations come first. why: they matter most.
```

`(user)` marks a decision that came from the user's own words. A decision's `why` keeps at most 18 words and `rejected` 12.

## Writing and compaction

- Write only through `kengash memory add`; the journal records who wrote each line and why.
- What goes where (SP16; `kengash context` prints it under `# Record`):
  - DECISIONS.md takes a settled choice later work must follow that the code does not make obvious: architecture and module boundaries, interfaces, data formats, libraries and tools, design-system values, platform or performance targets, a source of truth, naming.
  - MEMORY.md takes how the user works in every project: preferences, working style, goals, approaches turned down for good.
  - PROCESS.md takes how this project builds, tests or ships.
  - Never record one ticket's details, what the code or plan already says, a guess, or a secret.
- Near-duplicates (case, spacing, trailing punctuation; for decisions the date, why and rejected) count as recorded.
- The harvest records what the user settles without anyone remembering to (SP18). A one-shot job on `memory.compactor` reads the user's words at each moment below and writes each fact where it belongs. A fact whose `quote` is not in the user's own words is dropped. `memory.harvest`: `all`, `plans` or `off`.

  | Moment | What it reads |
  |---|---|
  | `plan approve`; a quick plan reaching `ticket add` | Prompt, Decisions, Assumptions |
  | `plan reject --why`, `approve --note` | the reason or answer |
  | Claude Code `PreCompact`, `SessionEnd` | the user's messages since the last read, registered projects only |

- `kengash memory forget "<words>"` removes one line. A harvested fact may overrule a listed decision, which then moves to the archive; pinned lines stay.
- Workers get `(user)` and pinned decisions first, then those naming the ticket's paths, then the newest.
- Plans write `## Lasting decisions` (`- <decision>. why: <reason>. rejected: <alternative>.`), recorded on approval; workers propose `decisions`, recorded when their ticket merges.
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
- `## Decisions` gathers what workers propose (at most 6) and lands in DECISIONS.md with the merge; `## Handoff` is replaced at every step; `## Check output` holds the last failing check and is cleared when checks pass; `## Log` gains one line per step and per in-step check run.
