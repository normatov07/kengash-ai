# store

## Purpose

Everything under `~/.harness`: paths, atomic writes, frontmatter documents, ids, locks, the registry, `.harness` links, seeding, and the store's own git history.

## Interface

- `StorePaths.default()` and `ProjectPaths`: the layout of system spec §4.1, plus `StorePaths.slots`, `claims`, `trust`, `flags`, `workers`, `ticket_states`, `conductors` and `logs` under `runtime/`, and `worktrees` with `worktree(slug, id)` (`worktrees/<slug>/hrn-<id>`); `HARNESS_HOME` overrides `~/.harness`.
- `seed.ensure_store`, `seed.ensure_project`: create folders and copy default files only when missing; `ensure_store` also seeds each package role skill missing from `defaults/roles/`.
- `documents`: `load_plan`, `load_ticket`, `load_any`, `save_plan`, `save_ticket` (a ticket lands in the folder its status names), `save_any`, `find_ticket`, `iter_documents`, `check_document`.
- `frontmatter.parse`, `frontmatter.split_frontmatter` (mapping and the text after it), `frontmatter.render`, `files.atomic_write`, `ids.new_id`, `locks.locked`, `yamlio.load_yaml`, `yamlio.dump_yaml`.
- `frontmatter.read_sections`: `## ` sections typed by an agent; unknown or repeated headings and text before the first heading are refused, and ``` fences are respected.
- `registry`: `load_registry`, `save_registry`, `slugify`, `unique_slug`, `slug_for_path`.
- `links`: `link_state`, `obstruction`, `make_link`, `ensure_excluded`, `is_excluded`.
- `redact.redact`: masks private keys, API tokens and the values assigned to names ending in `password`, `secret`, `token` or `api_key` (also `access_key`, `secret_key`, `private_key`), in any form: `DB_PASSWORD=…`, `token: …`, `"api_key": "…"`; quoted values are masked whole. Applied before anything reaches the journal or memory.
- `seed.package_default(name)`: a default file's text from the package.
- `runtime`: `load_slots`/`save_slots` (`runtime/slots.json`), `load_claims`/`save_claims` (`runtime/claims.json`), `load_trust`/`save_trust` (`runtime/trust.json`), worker records (`load_worker`, `load_workers`, `save_worker`, `drop_worker`, `beat`, `set_worker_step`; thread-safe within a process), ticket state (`load_ticket_state`, `save_ticket_state`, `drop_ticket_state`), park requests (`set_park`, `park_requested`: `flags/park-<id>`), `save_ping`, `load_cursor`/`save_cursor`, `pause_state` → `Pause(everything, projects)` and `set_pause(paths, slug or None, on=)` (`runtime/flags/`); a damaged file raises an error naming it.
- `storegit.commit_store`: commits every change as `harness`, never with the user's identity, hooks or signing.

## Invariants

- Only harness writes here; every write is a temp file, fsync and rename inside the real directory.
- A status move renames the file first and then rewrites it, so a crash leaves exactly one copy.
- `runtime/` and `worktrees/` stay out of the store's git.
- A content line that reads as a known `## ` heading is written with an extra leading backslash.
- Short ids never read as YAML numbers, so agents can list them unquoted.

## Changes

- 2026-10-23: `runtime.load_pings` (SP5 M1).
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
