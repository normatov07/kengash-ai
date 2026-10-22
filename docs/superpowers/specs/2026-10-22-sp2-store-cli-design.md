# Sub-project 2: Store and `harness` CLI — Spec

- Date: 2026-10-22
- Status: approved by default (user prefers momentum; assumptions listed in §2 for veto)
- Implements: system spec `2026-10-22-super-harness-design.md` §4 (store), §6 (store-only commands), units `model`, `store`, `settings`, `memory`, `journal`, `ops`, `cli`.
- This spec only adds what the system spec leaves open. Where they differ, change the system spec first.

## 1. Milestones

Each milestone is planned just before it is built (`docs/superpowers/plans/`), ends green on `make check`, and is reviewed against this spec.

| # | Milestone | Delivers | Exit |
|---|---|---|---|
| M1 | Store core | `model` (Plan, Ticket, Registry, errors), `store` (paths, atomic files, frontmatter, ids, locks, store git, registry, links, documents, seeding), `ops.projects` (init, doctor, link, adopt), CLI `init`, `doctor`, `link`, `adopt`, import-linter contracts | a repo registers, links, survives a move (`link`), repairs (`doctor --fix`) and adopts a real `.harness/` without data loss |
| M2 | Settings, memory, journal | `settings` (load, validate, resolve), `memory` (add, show, caps, redaction), `journal` (append, read), CLI `settings show\|get\|check`, `memory add\|show`, `context` | invalid SETTINGS.md is rejected with a hint; memory writes are capped, redacted and journaled |
| M3 | Plans and tickets | `ops.plans`, `ops.tickets`, `ops.status`; CLI `plan new\|save\|show\|approve\|reject`, `ticket add\|show\|list\|find\|set\|move`, `status` | a prompt becomes a plan, an approved plan becomes validated tickets, and ticket moves keep folders, statuses and dependencies consistent |

## 2. Decisions (assumed defaults — veto any)

1. **Dependencies:** `pydantic>=2.9` (schemas, and JSON Schema for SP3 structured output), `ruamel.yaml>=0.18` (round-trip YAML keeps SETTINGS.md comments), `filelock>=3.16` (locks). Dev: `import-linter>=2.1`. Nothing else.
2. **Store commits** run git with `-c user.name=harness -c user.email=harness@localhost -c commit.gpgsign=false -c core.hooksPath=/dev/null`, so they never depend on, prompt for, or trigger the user's git configuration.
3. **YAML:** frontmatter and registry are written by harness with block style for mappings and flow style for short lists (`depends_on: [a91b3d07]`). Timestamps are UTC, second precision, ISO 8601 with `Z`.
4. **Slugs:** folder name lowercased, every run of characters outside `[a-z0-9]` becomes `-`, trimmed; duplicates get `-2`, `-3`.
5. **`harness init [path]`** registers the git top-level when `path` is inside a repo; a plain folder may be registered with a warning (worktrees need git in SP3). It refuses (exit 4) when `<repo>/.harness` is a real folder and points to `harness adopt`.
6. **`harness adopt <path>`** never deletes data:
   - plans and tickets merge by `uuid`; on conflict the newer `updated` wins;
   - SETTINGS.md and PROCESS.md are taken from the folder only when the store has none;
   - the original folder, and any store copy that lost a conflict, move to `projects/<slug>/archive/adopted-<UTC stamp>/` (versioned by the store's git);
   - then the symlink replaces the folder.
7. **`harness doctor`** checks registry paths, links, the `.git/info/exclude` entry and every document (schema, and folder matching `status`). `--fix` repairs links and exclude entries only; it never edits documents. `--scan DIR` looks up to 3 levels deep for real `.harness/` folders. Exit 1 while problems remain.
8. **Interim plan approval:** until SP3 ships `harness plan review`, `harness plan approve` requires `--skip-review` whenever `plan.review_max > 0`; the plan records `review.skipped: true` and the journal records the skip.
9. **`harness ticket add --plan <id>`** reads a YAML or JSON list from stdin or `--file` (format in §4). Tickets reference each other through batch-local `key`s or existing ticket ids. Harness rejects unknown fields, unknown references and dependency cycles, then writes each ticket to `in_queue/ready`, or `in_queue/blocked` while any dependency is not done.
10. **Settings access:** agents never parse SETTINGS.md; `harness settings get <key>` prints one value, `show` prints the resolved file, `check` validates.
11. **Errors:** every command maps failures to the system spec exit codes (§6) and prints one line to stderr; `--json` prints machine output to stdout.
12. **Redaction** (M2) replaces common secrets with `[REDACTED]`: `sk-…`/`sk-ant-…` keys, `ghp_`/`github_pat_` tokens, `AKIA…` AWS keys, `xox[abp]-` Slack tokens, PEM private-key blocks, and `password|secret|token|api_key` assignments.

## 3. CLI reference

| Command | Output (default) | Exit codes |
|---|---|---|
| `harness init [PATH]` | `initialized <slug>: <repo>/.harness -> <store dir>` or `ok <slug>: already initialized`, plus warnings | 0 · 4 real `.harness/` folder · 1 path missing |
| `harness doctor [--fix] [--quiet] [--scan DIR]` | one line per problem; otherwise `ok: N projects` (nothing with `--quiet`) | 0 healthy · 1 problems remain |
| `harness link SLUG NEW_PATH` | `linked <slug>: <repo>/.harness -> <store dir>` | 0 · 1 unknown slug or path |
| `harness adopt PATH` | `adopted <slug>: N new, M conflicts; original kept in <archive>` | 0 · 1 nothing to adopt |
| `harness settings show\|get KEY\|check [--project SLUG]` | value or resolved YAML; `check` prints problems only | 0 · 1 invalid |
| `harness memory add TEXT --why WHY [--section S \| --decision [--rejected R]] [--project SLUG]` | `MEMORY.md +1 line (N/200)`; adds a cap warning when over | 0 · 1 |
| `harness memory show [--decisions] [--project SLUG]` | file content (filtered by project for decisions) | 0 |
| `harness context [--project SLUG]` | MEMORY.md, PROCESS.md headings, open gates | 0 · 4 store missing |
| `harness plan new --project SLUG --title T --mode grill\|direct\|quick` (prompt on stdin) | `plan <id> <status>` | 0 · 1 |
| `harness plan save ID` (Markdown sections on stdin) | `plan <id> draft, N sections` | 0 · 1 unknown section |
| `harness plan show ID` / `approve ID [--skip-review]` / `reject ID --why W` | plan file / `plan <id> approved` / `plan <id> rejected` | 0 · 1 · 5 review missing |
| `harness ticket add --plan ID [--file F]` | `N tickets: <ids> (R ready, B blocked)` | 0 · 1 invalid batch |
| `harness ticket show ID` / `list [--project] [--folder]` / `find TEXT` | file / one line per ticket / matches | 0 · 1 |
| `harness ticket set ID KEY=VALUE…` / `move ID FOLDER[/SUB] --why W` | `ticket <id> updated` / `ticket <id> → <status>` | 0 · 1 |
| `harness status [--project SLUG]` | per project: counts per folder, then gates waiting for the user | 0 |

## 4. `ticket add` input

```yaml
- key: keyring                      # batch-local name, optional
  title: Rotatable keyring with overlap window
  importance: critical              # simple | standard | critical
  gate: afk                         # afk | hitl (default afk)
  touches: [services/webhooks]      # repo path prefixes
  depends_on: []                    # batch keys or existing ticket ids
  tags: [payments]
  scope: |
    Keyring holds current and previous keys; signatures verify against both.
  acceptance:
    - Keyring accepts the previous key for a configurable overlap window
```

Harness fills `id`, `uuid`, `project`, `plan`, `workflow` (= importance), `loop: 1`, `loop_max` (from settings), `status`, `created`, `updated`, and renders `scope` and `acceptance` into the `## Scope` and `## Acceptance` sections.

## 5. Testing

- Every test gets its own `HARNESS_HOME` under `tmp_path` and real temporary git repos; no network, no global git config needed.
- CLI tests use Typer's `CliRunner` and assert on exit codes and output lines.
- Import-linter contracts (layers `cli > ops > memory, journal, settings > store > model`; `cli` may not import `store`) run in `make lint`.

## 6. Acceptance (SP2 exit)

- [ ] `harness init` in a git repo creates the store, the link and the exclude entry; a second run changes nothing.
- [ ] After moving a repo, `harness doctor` reports it and `harness link` repairs it; a broken link is fixed by `harness doctor --fix`.
- [ ] `harness adopt` merges by uuid, keeps every losing copy in the archive, and leaves the link in place.
- [ ] Settings, memory, plan and ticket commands behave as in §3, including caps, redaction, journal events, dependency validation and blocked → ready transitions.
- [ ] `make check` (with import-linter) is green; module docs exist for every new module.
