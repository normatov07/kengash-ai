# SP18: Automatic memory capture and wider ticket graphs

Status: approved in chat 2026-11-09 (user: "do what needs, analyse and implement the best ways to fix issues"; chat harvest accepted as the recommended option). Decisions marked *(call)* are the builder's.

## 1. Why

Measured on the live store, 2026-11-06 to 11-08.

| Memory | Number |
|---|---|
| `MEMORY.md` entries | 0 |
| `DECISIONS.md` entries, all written 11-08 | 14 |
| of those from the user's own words | 0 (13 workers at merge, 1 conductor) |
| Plan 8e191bdc Assumptions holding real design choices, none recorded | about 40 lines |
| Decisions that fit one worker's digest | 6 of 14 |
| Words per decision line (rule: about 20) | 34 to 70 |

The `memory` skill fires on words such as "always" or "we decided". The user writes "most importnat ones is caputuring animationa", which matches none.

| Parallelism | Number |
|---|---|
| Workers running when busy | mean 1.15, never above 2 |
| Loop minutes with at most 1 worker and nothing ready, no gate | 34% of 866 |
| Loop minutes with at most 1 worker and a ticket ready (mostly a merge gate, gone since `merge.mode: auto`) | 37% |
| chess-samurai graph | 26 tickets, 9 levels |
| Tickets now waiting behind one failed ticket | 7 of 9 queued |
| Of 86 independent ticket pairs: declared clash / really overlapped | 37 / 19 |
| Declared but not real / real but not declared | 27 / 9 |

Research: a preprint on 30 task pairs (Claim Plane, 2026) passed 6.7% of conflicting pairs with no coordination and 60.0% with file-level admission, equal to serial; broad declarations serialized 93.3% of clean work; line-level admission failed. Anthropic: coding suits parallel agents less than research does. Cognition: parallel writers conflict through implicit decisions, so decisions must be shared.

## 2. Goals and non-goals

Goals: what the user settles reaches memory without anyone remembering to write it; workers get the user's decisions first; ticket graphs come out wide, and a narrow one is visible before it is queued; path claims are accurate; one stuck ticket holding many is said out loud.

Non-goals: optimistic parallel edits (the study above); a new parallelism limit (`sessions.*` stays); a daemon (rule 7); UI changes beyond what the memory page already shows; chat capture on Codex or Antigravity, which have no session hooks kengash can use today.

Anti-goals: invented memories; a chat read outside a kengash project; a harvest failure ever failing the command that triggered it.

## 3. Design

### 3.1 Harvest job
`ops/harvest.py`, a detached one-shot job like compaction, on `memory.compactor` *(call: one cheap-worker setting)*. Work arrives as spool files in `runtime/harvest/`; one worker drains them oldest first and ends, so no process stays behind. A failed call keeps the entry for the next run, up to 3 attempts.

The output is `facts: [{kind, fact, why, rejected, quote, replaces}]`, `kind` one of `decision`, `preference`, `working_style`, `goal`, `turned_down`, `process`.

- `quote` must appear in the user's words, ignoring case and spacing, and hold at least 2 words. Otherwise the fact is dropped. This is the guard against invented memories.
- `replaces` is the number of a listed decision this one overrules (0: none); that line moves to the archive. A pinned line stays.
- At most 8 facts per entry; text capped at 16,000 characters, newest kept.
- The prompt lists what is already recorded, marks the text as data, and the call runs `read_only` with no tools.
- Text is redacted before it reaches the spool.

Decisions from a harvest, and an approved plan's Lasting decisions, carry `(user)`. `memory.harvest`: `all` (default), `plans`, `off`.

### 3.2 When it runs

| Moment | Text |
|---|---|
| `plan approve` | Prompt, Decisions, Assumptions |
| quick plan reaching `ticket add` | Prompt |
| `plan reject --why` | the reason |
| `approve --note` | the answer |
| Claude Code `PreCompact` and `SessionEnd` | the user's messages since the last harvest |

`kengash memory harvest --plan <id>` queues a plan by hand, for plans approved earlier.

### 3.3 Chat capture
`kengash memory harvest --hook` reads the hook JSON, always exits 0, and returns at once. It does nothing when `KENGASH_AGENT` is set (a worker), when the folder is not a registered project, or when `memory.harvest` is not `all`.

It keeps a byte offset per session in `runtime/harvest_cursors.json`, so each message is read once, and spends nothing under 8 new words. User messages and `AskUserQuestion` answers are quotable; the agent's preceding text (last 400 characters) is context only, so "yes, the second" can be understood but never quoted as agent words. Text pasted into a message with other words around it is left out, since a pasted document may carry words that are not the user's *(call)*; a message that is only a paste counts as theirs.

A plugin in the skills folder does not get its hooks loaded (probed live, Claude Code 2.1.319), so `kengash skills install --global` merges the two hooks into `~/.claude/settings.json`: once, keeping everything else, and leaving an unreadable file alone with a note *(call)*.

### 3.4 Lines that reach workers
- A decision's `why` keeps at most 18 words and `rejected` 12: first sentence, else first words.
- `digest(..., touches)`: pinned and `(user)` lines first, then lines naming the ticket's paths, then newest; printed in file order, without the date and tag. Cap 4,000 characters *(call: 2,500 held 6 lines)*.
- `(user)` is ignored by duplicate detection.
- `kengash memory forget "<text>"` removes one matching line from MEMORY, DECISIONS or the project's PROCESS; zero or several matches is an error.
- `kengash context` lists the last 5 harvested lines of the past week, so the conductor can tell the user.

### 3.5 Plans must say what lasts
`plan save` of a non-quick plan that includes `## Goal` is refused without a `## Lasting decisions` section; `none` is allowed. The plan reviewer checks it covers every choice later tickets must follow.

### 3.6 Graph shape
- Every `depends_on` entry needs a `needs` line saying what this ticket uses from it; `ticket add` refuses one without. The lines are appended to the ticket's Scope, so the implementer reads them.
- `ticket add --check` creates nothing and prints: levels and widest level; chokepoints (a ticket past the first level with at least max(3, n/4) tickets behind it); pairs that will run one at a time and the shared file; top-level folders claimed; hot files claimed by unordered tickets.
- Hot files: files changed by at least 3 tickets in the last 400 kengash commits (`gitops.hot_files`).
- `ticket add` prints the shape line too. The `ticket` skill runs `--check` first and reshapes once.

### 3.7 Claims that match the edits
- `paths.shared` gains `test/`, `tests/`, `test`, `tests`: a claim on a whole test root no longer clashes; two tickets naming the same test file still do *(call: the pattern matches the folder claim only)*.
- After an editing step, files the branch changed outside `touches` join `touches` (shared patterns excluded), so later tickets wait for them. A clash this creates is journaled as `ticket.overlap` and noted in the Log; the merge queue's recheck still judges the result.

### 3.8 Say what is stuck
A ticket at a gate or parked, with at least 3 unfinished tickets behind it transitively, is listed by `kengash next` and `kengash watch`: `waiting on <id> (<status>): N tickets behind it`.

## 4. Testing
Unit tests per module with the existing fake CLIs. A test fixture stops the detached start; spool contents prove each trigger. Live proof on the real store: `memory harvest --plan 8e191bdc`, and one Claude Code session that advances a cursor.

## 5. Left out
Codex and Antigravity chat capture; a desktop notification for stuck tickets; line-level claims.
