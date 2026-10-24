# settings

## Purpose

Resolve SETTINGS.md into a validated `Settings` model so agents never parse the file themselves.

## Interface

- `load(paths, slug=None)` → `Settings`: package defaults, then `~/.harness/defaults/SETTINGS.md`, then `projects/<slug>/SETTINGS.md`. Raises `UserError` naming the first problem: `settings: …` for schema problems, or the file name for invalid YAML.
- `problems(paths, slug=None)` → one line per problem, empty when valid (`harness settings check`).
- `get(settings, key)` → the value at a dotted key, with a "did you mean" hint for unknown keys.
- `unflatten`, `merge`: the YAML rules below, usable on any mapping.
- `set_values(paths, slug|None, changes)` → the keys changed: writes dotted keys (None removes one) into `defaults/SETTINGS.md` or the project's file through `store.yamledit`, validates the resolved result first and writes nothing on a problem (`UserError` naming it); a defaults save also resolves every registered project with the new defaults and is refused, naming the project and its first problem, when one that resolved before would no longer validate; `workflows.<name>` is set whole. `scope_keys(paths, slug)` → the dotted leaves that file sets, a workflow counting as one; `overrides(paths, slug)` → those whose resolved value differs from what the scope inherits (package defaults for the user's defaults, the user's defaults for a project), since a project's file starts as a full copy.

## Invariants

- Dotted keys nest (`loop_max.simple: 3`); the same key set twice is an error.
- Mappings deep-merge, so a project can override one field of one agent; each `workflows.<name>` is replaced whole, so steps and `on_fail` never mix across files.
- Unknown keys fail with the closest known key as a hint.
- Reading never writes. Writes (`set_values`) keep comments, every line they do not change and the file's line ending (CRLF stays CRLF); `ops.configure` locks, journals and commits them.

## Changes

- 2026-10-24: writes keep a CRLF file's line endings.
- 2026-10-24: a defaults save is refused when a registered project would no longer validate.
- 2026-10-23: comment-preserving writes, `scope_keys`, `overrides` (SP5 M2).
- 2026-10-22: layered load, validation with hints, dotted-key get (SP2 M2).
