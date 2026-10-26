# journal

## Purpose

The append-only event log behind monitoring, the UI's live view and the audit trail: who did what, with which model, and why.

## Interface

- `append(paths, event)`: one JSON line in `journal/YYYY-MM-DD.jsonl` (UTC day of `event.ts`).
- `read(paths, since=None)` → `Event`s in file order, from day `since`; `days(paths)` → the day files, oldest first; `read_day(path)` → one day's events.
- `read_after(paths, cursor)` → the events after a `JournalCursor` (day file and line) and the cursor at the end; `end(paths)` → the cursor after the last event. `harness wait` reports each event once this way.

## Invariants

- Lines are never rewritten or deleted.
- Every string is redacted before it is written; files are mode 0600.
- One `os.write` per line with `O_APPEND`, so concurrent writers never interleave inside a line.

## Changes

- 2026-10-26: the package is `kengash_ai` (the app is Kengash AI, distributed as `kengash-ai`; SP7 spec decision 16).
- 2026-10-23: `days`, `read_day` (SP5 M2: the UI parses each past day once).
- 2026-10-23: journal positions: `read_after`, `end` (SP3 M3).
- 2026-10-22: append and read (SP2 M2).
