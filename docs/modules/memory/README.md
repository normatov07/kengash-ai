# memory

## Purpose

The agents' long-term memory: MEMORY.md (who the user is, how they work, what they want and have turned down) and DECISIONS.md (what was decided, why, and what was rejected).

## Interface

- `digest(paths, project, root, touches)` ranks decisions (SP18 spec §3.4); `forget(paths, text, project, by=)` removes one line; `supersede(paths, line, by=)` archives an overruled decision; `harvested(paths, project)` lists what the harvest wrote; `decision_lines`, `memory_lines`.
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

- 2026-11-09: `add(..., user=)` marks a decision `(user)`; `why` and `rejected` are tightened; digest cap for decisions is 4,000 characters (SP18).
- 2026-11-08: `is_pinned` is public, for the compactor's repair turn (SP17 live run).
- 2026-11-08: a path too long for the filesystem counts as gone instead of raising on 3.12 and 3.13 (SP17 minors).
- 2026-11-08: `digest(paths, project, root=None)`: with the code's root, a process or decision line naming a file that is gone is tagged `[stale? path gone: …]`, not hidden; age plays no part (SP17).
- 2026-11-07: `RECORD_HINT` separates a design decision for this project from how the user works in every project (haiku dry runs: 5/5 filed each kind right) (SP16).
- 2026-11-07: `decision_text(decision, why, rejected)` renders a decision line (SP16).
- 2026-11-07: `parse_decision(line)` → (decision, why, rejected) from `<decision>. why: … rejected: ….` (SP16).
- 2026-11-07: `key(line)`: near-duplicates count as recorded (lowercased, spaces collapsed, trailing punctuation dropped; a decision compares tag and decision only); `add_process(paths, text, why=, project=, by=)` appends under `## Process notes` of the project's PROCESS.md (cap 100, refused at the cap), journaled and committed; `RECORD_HINT`: when to record what (SP16).
- 2026-11-07: `digest(paths, project)`: the `## Memory` body of every new worker session: the head of the project's PROCESS.md (from its first `## `, 3,000 characters), the newest `[project]` and `[global]` DECISIONS.md entries (2,500) and the newest MEMORY.md entries as `- [<section>] text` (1,500), with `… N older/more lines in <file>` notes, redacted (SP16).
- 2026-10-26: messages name the `kengash` command; `KengashError` replaces `HarnessError` (SP8).
- 2026-10-26: store commits `kengash: memory …`; compaction events `by: kengash` (SP8).
- 2026-10-26: the package is `kengash_ai` (the app is Kengash AI, distributed as `kengash-ai`; SP7 spec decision 16).
- 2026-10-23: DECISIONS archive (SP3 M4).
- 2026-10-23: compaction checks and writes (SP3 M4).
- 2026-10-22: any line break is refused, not only `\n` (SP2 M2 review).
- 2026-10-22: add and show with caps, redaction, journal and store commits (SP2 M2).
