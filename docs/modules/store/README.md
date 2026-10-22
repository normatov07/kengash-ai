# store

## Purpose

Everything under `~/.harness`: paths, atomic writes, frontmatter documents, ids, locks, the registry, `.harness` links, seeding, and the store's own git history.

## Interface

- `StorePaths.default()` and `ProjectPaths`: the layout of system spec §4.1; `HARNESS_HOME` overrides `~/.harness`.
- `seed.ensure_store`, `seed.ensure_project`: create folders and copy default files only when missing.
- `documents`: `load_plan`, `load_ticket`, `load_any`, `save_plan`, `save_ticket` (a ticket lands in the folder its status names), `save_any`, `find_ticket`, `iter_documents`, `check_document`.
- `frontmatter.parse`, `frontmatter.render`, `files.atomic_write`, `ids.new_id`, `locks.locked`, `yamlio.load_yaml`, `yamlio.dump_yaml`.
- `registry`: `load_registry`, `save_registry`, `slugify`, `unique_slug`, `slug_for_path`.
- `links`: `link_state`, `obstruction`, `make_link`, `ensure_excluded`, `is_excluded`.
- `redact.redact`: masks private keys, API tokens and the values assigned to names ending in `password`, `secret`, `token` or `api_key` (also `access_key`, `secret_key`, `private_key`), in any form: `DB_PASSWORD=…`, `token: …`, `"api_key": "…"`; quoted values are masked whole. Applied before anything reaches the journal or memory.
- `seed.package_default(name)`: a default file's text from the package.
- `storegit.commit_store`: commits every change as `harness`, never with the user's identity, hooks or signing.

## Invariants

- Only harness writes here; every write is a temp file, fsync and rename inside the real directory.
- A status move renames the file first and then rewrites it, so a crash leaves exactly one copy.
- `runtime/` and `worktrees/` stay out of the store's git.
- A content line that reads as a known `## ` heading is written with an extra leading backslash.

## Changes

- 2026-10-22: redaction also catches prefixed names, JSON keys and quoted values, in linear time (SP2 M2 review).
- 2026-10-22: redaction and `package_default` (SP2 M2).
- 2026-10-22: `link_state` accepts a link whose target resolves to the project folder through a symlinked path.
- 2026-10-22: store core: layout, atomic files, frontmatter, documents, ids, locks, registry, links, seeding, store git (SP2 M1).
