# settings

## Purpose

Resolve SETTINGS.md into a validated `Settings` model so agents never parse the file themselves.

## Interface

- `load(paths, slug=None)` → `Settings`: package defaults, then `~/.kengash/defaults/SETTINGS.md`, then `projects/<slug>/SETTINGS.md`. Raises `UserError` naming the first problem: `settings: …` for schema problems, or the file name for invalid YAML. Each layer is parsed once per content and the resolved `Settings` cached by the layers' digests; callers get copies, and errors are never cached (SP7).
- `problems(paths, slug=None)` → one line per problem, empty when valid (`kengash settings check`).
- `get(settings, key)` → the value at a dotted key, with a "did you mean" hint for unknown keys.
- `unflatten`, `merge`: the YAML rules below, usable on any mapping.
- `set_values(paths, slug|None, changes)` → the keys changed: writes dotted keys (None removes one) into `defaults/SETTINGS.md` or the project's file through `store.yamledit`, validates the resolved result first and writes nothing on a problem (`UserError` naming it); a defaults save also resolves every registered project with the new defaults and is refused, naming the project and its first problem, when one that resolved before would no longer validate; `workflows.<name>` is set whole. `scope_keys(paths, slug)` → the dotted leaves that file sets, a workflow counting as one; `overrides(paths, slug)` → those whose resolved value differs from what the scope inherits (package defaults for the user's defaults, the user's defaults for a project), since a project's file starts as a full copy.

## Invariants

- Dotted keys nest (`loop_max.simple: 3`); the same key set twice is an error.
- Mappings deep-merge, so a project can override one field of one agent; each `workflows.<name>` is replaced whole, so steps and `on_fail` never mix across files, and so is an agent's `by_importance`, so a project can clear what the defaults set.
- Unknown keys fail with the closest known key as a hint.
- Reading never writes. Writes (`set_values`) keep comments, every line they do not change and the file's line ending (CRLF stays CRLF); `ops.configure` locks, journals and commits them.

## Changes

- 2026-11-08: `WHOLE`: `by_importance` is replaced whole by a narrower scope (SP17).
- 2026-11-06 (SP12 minors): `set_values` setting a renamed key's new name renames the old key on its own line (`yamledit.rename_key`), keeping its place and comment.
- 2026-11-06: `scope_layer(paths, slug)`: one scope's own file as written, renamed keys under their old names (SP12 M3).
- 2026-11-06: `RENAMED` (`fallback_on_rate_limit` → `fallback_on_error`): each layer reads the old key under the new name and refuses both in one file; `set_values` setting the new key drops the old one from that file (SP12 M1).
- 2026-10-26: the package is `kengash_ai` (the app is Kengash AI, distributed as `kengash-ai`; SP7 spec decision 16).
- 2026-10-26: content-keyed layer and resolve caches (SP7).
- 2026-10-24: writes keep a CRLF file's line endings.
- 2026-10-24: a defaults save is refused when a registered project would no longer validate.
- 2026-10-23: comment-preserving writes, `scope_keys`, `overrides` (SP5 M2).
- 2026-10-22: layered load, validation with hints, dotted-key get (SP2 M2).
