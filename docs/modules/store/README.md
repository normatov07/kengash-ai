# store

## Purpose

Everything under `~/.kengash`: paths, atomic writes, frontmatter documents, ids, locks, the registry, `.kengash` links, seeding, and the store's own git history.

## Interface

- `StorePaths.default()` and `ProjectPaths`: the layout of system spec §4.1, plus `StorePaths.slots`, `claims`, `trust`, `flags`, `workers`, `ticket_states`, `conductors` and `logs` under `runtime/`, and `worktrees` with `worktree(slug, id)` (`worktrees/<slug>/kg-<id>`, or a ticket's existing 0.1.0 `hrn-<id>`); `KENGASH_HOME` (then 0.1.0's `HARNESS_HOME`) overrides `~/.kengash`.
- `seed.ensure_store`, `seed.ensure_project`: create folders and copy default files only when missing; role skills are not seeded since SP10 (built-in ones always load from the package); `seed.link_memory(paths, project)` points a project's `memory` at `../../memory`, replacing a missing or stale link but never a real file or folder.
- `documents`: `load_plan`, `load_ticket` (each parsed once per file content and returned as a copy, SP7), `load_any`, `save_plan`, `save_ticket` (a ticket lands in the folder its status names), `save_any`, `find_ticket`, `iter_documents`, `check_document`.
- `frontmatter.parse`, `frontmatter.split_frontmatter` (mapping and the text after it), `frontmatter.render`, `files.atomic_write`, `ids.new_id`, `locks.locked`, `yamlio.load_yaml` (a per-thread YAML 1.2 safe loader, C-accelerated by `ruamel.yaml.clib`), `yamlio.dump_yaml`. `memo.Memo` (thread-safe LRU, `get_or_make`) and `memo.digest` key parse caches by file content, never by stat: an in-place rewrite within one timestamp tick keeps size and inode.
- `yamledit.set_key(text, key, value, source=)`: one dotted key set (None removes it) with every other line byte-identical; the longest dotted prefix present wins at each mapping; a one-line scalar is swapped in place, anything else rewrites the nearest block-mapping entry on one line in flow style (the spacing after its key and its trailing comment kept); a removal that empties a block drops the block. Every line it writes ends as the text's first line does, so a CRLF file stays CRLF (an unterminated last line stays unterminated). `yamledit.flow(value)`: one-line flow YAML, quoting strings that would not read back as themselves.
- `frontmatter.read_sections`: `## ` sections typed by an agent; unknown or repeated headings and text before the first heading are refused, and ``` fences are respected.
- `registry`: `load_registry`, `save_registry`, `slugify`, `unique_slug`, `slug_for_path`.
- `links`: `link_state`, `state_of` (any folder link, e.g. a project's `memory`), `obstruction`, `make_link`, `ensure_excluded`, `is_excluded`.
- `redact.redact`: masks private keys, API tokens and the values assigned to names ending in `password`, `secret`, `token` or `api_key` (also `access_key`, `secret_key`, `private_key`), in any form: `DB_PASSWORD=…`, `token: …`, `"api_key": "…"`; quoted values are masked whole. Applied before anything reaches the journal or memory.
- `seed.package_default(name)`: a default file's text from the package.
- `runtime`: `load_slots`/`save_slots` (`runtime/slots.json`), `load_claims`/`save_claims` (`runtime/claims.json`), `load_trust`/`save_trust` (`runtime/trust.json`), worker records (`load_worker`, `load_workers`, `save_worker`, `drop_worker`, `beat`, `set_worker_step`; thread-safe within a process), ticket state (`load_ticket_state`, `save_ticket_state`, `drop_ticket_state`), park requests (`set_park`, `park_requested`: `flags/park-<id>`), `save_ping`, `load_cursor`/`save_cursor`, `pause_state` → `Pause(everything, projects)` and `set_pause(paths, slug or None, on=)` (`runtime/flags/`); a damaged file raises an error naming it.
- `storegit.commit_store`: commits every change as `kengash`, never with the user's identity, hooks or signing.

## Invariants

- Only kengash writes here; every write is a temp file, fsync and rename inside the real directory.
- A status move renames the file first and then rewrites it, so a crash leaves exactly one copy.
- `runtime/` and `worktrees/` stay out of the store's git.
- A content line that reads as a known `## ` heading is written with an extra leading backslash.
- Short ids never read as YAML numbers, so agents can list them unquoted.

## Changes

- 2026-10-30: `ensure_store` no longer seeds `defaults/roles/` (SP10 M2).
- 2026-10-30: `defaults/SETTINGS.md` explains `routing` in a comment (SP10 M2).
- 2026-10-26: the seeded MEMORY.md, DECISIONS.md and SETTINGS.md name `kengash` (SP8).
- 2026-10-26: `StorePaths.worktree` is `worktrees/<slug>/kg-<id>`, or the ticket's existing 0.1.0 `hrn-<id>` folder (SP8).
- 2026-10-26: the repo link is `.kengash` (`links.LINK`, exclude `/.kengash`); `links.real_folder` finds a real `.kengash/` or 0.1.0 `.harness/`; `links.legacy_link` names a 0.1.0 `.harness` symlink to the same project (SP8).
- 2026-10-26: the store is `~/.kengash` (`KENGASH_HOME`, then `HARNESS_HOME`; `kengash_home()`); `migrate.legacy_home()` moves a plain `~/.harness` there once and leaves `~/.harness` linking to it, never merging two real folders or moving a custom location (SP8).
- 2026-10-26: the package is `kengash_ai` (the app is Kengash AI, distributed as `kengash-ai`; SP7 spec decision 16).
- 2026-10-26: defaults `sessions.per_provider` drops gemini (SP7).
- 2026-10-26: defaults SETTINGS.md documents `logs.keep_days` (SP7).
- 2026-10-26: `memo` parse caches; cached document loads; C-accelerated safe YAML (SP7).
- 2026-10-24: `yamledit` keeps a CRLF file's line ending on every line it writes.
- 2026-10-23: `yamledit` (SP5 M2 settings writes).
- 2026-10-23: `links.state_of` (any folder link), `seed.link_memory` (system spec §4.2).
- 2026-10-23: `runtime.load_pings`; `runtime/ui.json` (`load_ui`, `save_ui` at mode 0600, `drop_ui`) (SP5 M1).
- 2026-10-23: role skills seeded into `defaults/roles/`; `split_frontmatter` (SP4 M1).
- 2026-10-23: worker records, ticket state, park flags, conductor pings and wait cursors (SP3 M3).
- 2026-10-23: `runtime/trust.json` (SP3 M2).
- 2026-10-22: runtime slots, claims and pause flags (SP3 M1).
- 2026-10-22: default SETTINGS.md adds `memory.compactor`, `providers` and the `bypass_permissions` note (SP3 M1).
- 2026-10-22: `read_sections`; ids never read as numbers (SP2 M3).
- 2026-10-22: redaction also catches prefixed names, JSON keys and quoted values, in linear time (SP2 M2 review).
- 2026-10-22: redaction and `package_default` (SP2 M2).
- 2026-10-22: `link_state` accepts a link whose target resolves to the project folder through a symlinked path.
- 2026-10-22: store core: layout, atomic files, frontmatter, documents, ids, locks, registry, links, seeding, store git (SP2 M1).
