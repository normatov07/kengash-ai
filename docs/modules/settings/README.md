# settings

## Purpose

Resolve SETTINGS.md into a validated `Settings` model so agents never parse the file themselves.

## Interface

- `load(paths, slug=None)` → `Settings`: package defaults, then `~/.harness/defaults/SETTINGS.md`, then `projects/<slug>/SETTINGS.md`. Raises `UserError` naming the first problem: `settings: …` for schema problems, or the file name for invalid YAML.
- `problems(paths, slug=None)` → one line per problem, empty when valid (`harness settings check`).
- `get(settings, key)` → the value at a dotted key, with a "did you mean" hint for unknown keys.
- `unflatten`, `merge`: the YAML rules below, usable on any mapping.

## Invariants

- Dotted keys nest (`loop_max.simple: 3`); the same key set twice is an error.
- Mappings deep-merge, so a project can override one field of one agent; each `workflows.<name>` is replaced whole, so steps and `on_fail` never mix across files.
- Unknown keys fail with the closest known key as a hint.
- Reading never writes: comment-preserving edits arrive with the UI (SP5).

## Changes

- 2026-10-22: layered load, validation with hints, dotted-key get (SP2 M2).
