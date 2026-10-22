# memory

## Purpose

The agents' long-term memory: MEMORY.md (who the user is, how they work, what they want and have turned down) and DECISIONS.md (what was decided, why, and what was rejected).

## Interface

- `add(paths, text, why, *, section, decision, rejected, project, by)` → `AddResult(file, line, lines, cap, added)`; `.over_cap` when the file passed its cap.
- `show(paths, *, decisions, project)` → MEMORY.md, or DECISIONS.md narrowed to one project's entries plus the `[global]` ones.
- `SECTIONS`: `Working style`, `Goals`, `Preferences`, `Turned down`.

## Invariants

- One line per fact, at most 30 words; empty or multi-line text is refused.
- Text is redacted before it is written; identical lines are not added twice.
- Every write is journaled (`memory.write` with `file`, `line`, `why`, `by`) and committed to the store's git.
- Caps: MEMORY.md `memory.compact_at_lines` (200) from the user's defaults, because the file is global; DECISIONS.md 300. Passing a cap is reported, not blocked; compaction arrives with the engine (SP3).

## Changes

- 2026-10-22: add and show with caps, redaction, journal and store commits (SP2 M2).
