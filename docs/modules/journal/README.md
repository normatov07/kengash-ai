# journal

## Purpose

The append-only event log behind monitoring, the UI's live view and the audit trail: who did what, with which model, and why.

## Interface

- `append(paths, event)`: one JSON line in `journal/YYYY-MM-DD.jsonl` (UTC day of `event.ts`).
- `read(paths, since=None)` → `Event`s in file order, from day `since`.
- `read_after(paths, cursor)` → the events after a `JournalCursor` (day file and line) and the cursor at the end; `end(paths)` → the cursor after the last event. `harness wait` reports each event once this way.

## Invariants

- Lines are never rewritten or deleted.
- Every string is redacted before it is written; files are mode 0600.
- One `os.write` per line with `O_APPEND`, so concurrent writers never interleave inside a line.

## Changes

- 2026-10-23: journal positions: `read_after`, `end` (SP3 M3).
- 2026-10-22: append and read (SP2 M2).
