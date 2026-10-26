# memory

## Purpose

The agents' long-term memory: MEMORY.md (who the user is, how they work, what they want and have turned down) and DECISIONS.md (what was decided, why, and what was rejected).

## Interface

- `add(paths, text, why, *, section, decision, rejected, project, by)` → `AddResult(file, line, lines, cap, added, compacting)`; `.over_cap` when the file passed its cap; `ops` sets `compacting` when the add started a compaction.
- `show(paths, *, decisions, project)` → MEMORY.md, or DECISIONS.md narrowed to one project's entries plus the `[global]` ones.
- Compaction (SP3 spec decision 31): `compaction_problem(current, result, cap)` (empty, a dropped pinned entry, a dropped `##` heading, or not under the cap), `merge_added(snapshot, current, result)` (entries written meanwhile go into their sections), `apply_compaction(paths, snapshot, text, cap=, detail=)` → `Compaction(before, after, accepted, reason)`: under `memory.lock`, redacted, `memory.compacted` journaled either way, committed when accepted.
- DECISIONS archive (SP3 spec decision 32): a decision that takes DECISIONS.md past 300 lines moves its oldest entries, oldest first, to `memory/archive/DECISIONS.md` (`archive_oldest`, `ARCHIVE_HEADER`); `memory.write` then has `archived`.
- `SECTIONS`: `Working style`, `Goals`, `Preferences`, `Turned down`.

## Invariants

- One line per fact, at most 30 words; empty text, or text with any line break (`\n`, `\r`, U+2028…), is refused.
- Text is redacted before it is written; identical lines are not added twice.
- Every write is journaled (`memory.write` with `file`, `line`, `why`, `by`) and committed to the store's git.
- Caps: MEMORY.md `memory.compact_at_lines` (200) from the user's defaults, because the file is global; DECISIONS.md 300, kept by the archive. Passing a cap is reported, not blocked; `ops` then compacts MEMORY.md in the background. A pinned entry is a `- ` line containing `(pin)`.

## Changes

- 2026-10-26: store commits `kengash: memory …`; compaction events `by: kengash` (SP8).
- 2026-10-26: the package is `kengash_ai` (the app is Kengash AI, distributed as `kengash-ai`; SP7 spec decision 16).
- 2026-10-23: DECISIONS archive (SP3 M4).
- 2026-10-23: compaction checks and writes (SP3 M4).
- 2026-10-22: any line break is refused, not only `\n` (SP2 M2 review).
- 2026-10-22: add and show with caps, redaction, journal and store commits (SP2 M2).
