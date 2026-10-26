# SP8: Kengash naming (design)

Date: 2026-10-26. Status: written under the user's instruction to rename commands "and all things" after the new name, with best practices; calls marked *call* are open to veto.

## 1. Why

The app is Kengash AI (SP7 decision 16), published as `kengash-ai` 0.1.0, but everything a user types or sees still says harness: the `harness`/`hrn` commands, `~/.harness`, the `.harness` link in each repo, `HARNESS_HOME`/`HARNESS_AGENT`, `hrn(<id>)` commit subjects, `Harness-*` trailers, `hrn/<id>` branches, the `X-Harness` header, `harness: …` store commits and the `harness-memory` skill. A 0.1.0 install exists, so the rename must keep it working.

Research (2026-10-26): clig.dev — a simple memorable lowercase name, aliases explicit and stable, very short names reserved for common utilities, warn before a non-additive change, environment variables are interfaces. Salesforce CLI and GNU Guix — keep a deprecated name working for a fixed window while it warns and names the replacement. The Mux → Xum rename — move the old data folder only when the new one is absent, leave the old path as a link so old binaries and links keep working, never merge or delete two real folders, never move custom locations, the new environment variable wins.

## 2. Goals, non-goals, anti-goals

- Goals: every name a user types or sees is kengash; a 0.1.0 user upgrades without doing anything and loses no store data, link, ticket branch or worktree; the old names keep working through 0.2.x with a warning.
- Non-goals: an XDG data directory (the store stays one visible folder in home, linked into projects); renaming file formats or settings keys.
- Anti-goals: a migration that can lose or merge data; a warning on stdout (it would break `--json`); breaking a ticket that is running during the upgrade.

## 3. Decisions

1. **Command `kengash`.** `harness` and `hrn` stay as deprecated entry points through 0.2.x: invoked under an old name, the CLI prints one stderr line, `harness is now kengash; the harness and hrn names stop working in 0.3.0`, then runs normally. No new short alias: `kg` collides with the common `kubectl get` shell alias (*call*).
2. **Store `~/.kengash`.** `KENGASH_HOME` names it; `HARNESS_HOME` is read when `KENGASH_HOME` is unset. The CLI calls `store.migrate.legacy_home()` (through `ops.projects.migrate_home`) before any command; every other process — workers, the UI server, eval conductors — is started by the CLI, so this one entry point covers them: with neither variable set, `~/.kengash` absent and `~/.harness` a real directory, it renames `~/.harness` to `~/.kengash` and creates `~/.harness → ~/.kengash`, so running workers, 0.1.0 binaries, project links and git worktree records that hold the old path keep resolving. Both real directories: nothing moves; `~/.kengash` is used and `doctor` reports the leftover. Custom locations are never moved.
3. **Project link `.kengash`.** `init`, `link` and `adopt` write `<repo>/.kengash` and its `.git/info/exclude` line. A repo still holding a `.harness` link is reported by `doctor`; `doctor --fix` replaces it with `.kengash` (same target, the new store path). `adopt` and the nearby-store scan accept a real `.kengash/` or legacy `.harness/` folder.
4. **Agent variable `KENGASH_AGENT`.** Workers set it; `--by` and the conductor reading take `KENGASH_AGENT`, then `HARNESS_AGENT`.
5. **Git conventions.** New commits: subject `kg(<id>): loop N step: …`, trailers `Kengash-Ticket`, `Kengash-Model`; new branches `kg/<id>`, worktrees `worktrees/<slug>/kg-<id>`. Readers accept both forms: `Harness-*` trailers, `hrn(` subjects; a ticket keeps the branch it was claimed with; a worktree path resolves to an existing `hrn-<id>` folder first.
6. **UI.** Header `X-Kengash`, cookie `kengash_token_{port}`; the screens and server ship together, so the old names are not accepted.
7. **Store and journal.** Store commits read `kengash: …`; events the engine writes carry `by: kengash`. Older entries stay as written.
8. **Skills.** `harness-memory` becomes `kengash-memory`; every skill and role skill uses `kengash`; step 0 runs `kengash --version` and expects `kengash-ai <version>`; `skills install --cli-name` defaults to `kengash`. Installing removes an installed skill folder that is not packaged any more only when its frontmatter says `source: kengash-ai` or `source: super-harness` (ours); anything else is left alone. The PATH clash check looks for `kengash`.
9. **Version 0.2.0**, with a CHANGELOG "Changed", "Deprecated" and upgrade note.
11. **Every other name, reviewed.** Kept: the slash commands the original request named, `/to-plan`, `/to-plan-with-grill`, `/to-ticket`, `/to-loop`, `/open-ui` (installed as a Claude Code plugin they are namespaced as `/kengash-ai:<name>` automatically); the role skills `plan`, `review-plan`, `implement`, `review-code`, `review-security`, `run-tests`, `sync-docs` and role names (they describe roles, not the product); the store's folders, files and settings keys; the Python package `kengash_ai` and the distribution `kengash-ai`. Renamed: the memory skill (decision 8) and the system spec file, `2026-10-22-super-harness-design.md` → `2026-10-22-kengash-design.md`, with every living reference updated (old plans keep theirs as history).
10. **Prose.** "harness" stays where it names the concept (an agent harness, harness engineering); where it named the CLI or the store it becomes kengash.

## 4. Acceptance (SP8 exit)

- [x] `kengash --version` prints `kengash-ai 0.2.0`; `harness`/`hrn` run the same command, warn once on stderr, and leave `--json` output parseable.
- [x] A 0.1.0 home (`~/.harness` with a registered project, a `.harness` link and a ticket worktree) migrates on first run: `~/.kengash` holds the data, `~/.harness` links to it, the old link and worktree still resolve, `doctor --fix` turns the link into `.kengash`; both-real-directories and custom-location cases move nothing.
- [x] New commits, branches and worktrees use the kengash forms; changes, merge and the ticket sheet still read a 0.1.0 branch.
- [x] Skills install as `kengash-memory` etc., an old `harness-memory` of ours is removed and a foreign one is kept; `kengash skills lint` passes.
- [x] The UI works end to end in Chrome with the new header and cookie.
- [x] `make check` and `make dist` green; module docs, README, AGENTS.md, architecture and the system spec say kengash.

Evidence (2026-10-26): `tests/test_cli.py` (console scripts, clean `--json` under `hrn`), `tests/test_store_migrate.py`, `tests/test_ops_projects.py` (legacy links), `tests/test_gitops.py` and `tests/test_ops_merging.py` (0.1.0 tickets), `tests/test_ops_skills.py` (obsolete skills); a real `kengash-ai==0.1.0` store from PyPI moved by the first `kengash` command, its old project link and the 0.1.0 binary still working, `doctor --fix` turning `.harness` into `.kengash`; the UI on that store in headless Chrome (store path, brand, a New agent POST with `X-Kengash`); `make check` 637 passed.
