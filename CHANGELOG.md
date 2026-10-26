# Changelog

All notable changes to this project are written here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [0.2.0] - unreleased

### Changed

- Everything is named after Kengash: the command is `kengash`, the store `~/.kengash` (`KENGASH_HOME`), each project's link `.kengash`, the agent variable `KENGASH_AGENT`; new ticket commits read `kg(<id>): …` with `Kengash-*` trailers on `kg/<id>` branches; the UI's change header is `X-Kengash`; store commits read `kengash: …`; the memory skill is `kengash-memory`.
- The first `kengash` command moves a 0.1.0 `~/.harness` to `~/.kengash` once and leaves `~/.harness` linking to it; it never merges two folders or moves a location an environment variable chose. `kengash doctor --fix` replaces old `.harness` project links, and `kengash skills install` removes the old `harness-memory` skill it installed.
- Tickets claimed under 0.1.0 keep their `hrn/` branches and worktrees, and their `Harness-*` commits are still read.

### Deprecated

- The `harness` and `hrn` commands, `HARNESS_HOME` and `HARNESS_AGENT` still work and warn; the commands stop working in 0.3.0.

## [0.1.0] - 2026-10-26

The first release.

### Added

- `harness` CLI: projects and the store (`init`, `doctor`, `link`, `adopt`), plans and tickets, settings and memory, the engine controls (`next`, `run`, `wait`, `approve`, `park`, `stop`, `pause`, `resume`, `merge`), skills (`install`, `lint`, `eval`) and the UI (`ui open`, `ui stop`).
- An engine that runs each ticket through an importance-based workflow on `claude`, `codex` and `agy` under the user's login, one detached worker per job, one git worktree per ticket, with loop caps, token caps, stall detection, plan review and memory compaction.
- Installed skills: `to-plan`, `to-plan-with-grill`, `to-ticket`, `to-loop`, `harness-memory`, `open-ui`; seven role skills.
- A local web UI: overview, task board, ticket sheet with changes and timeline, workflow editor, agents and providers, settings and memory, live over server-sent events.
- Custom agents: `steps.<name>: {role, kind, does}` in SETTINGS.md, `harness agent new|remove`, and the UI's New agent dialog.
- Log retention (`logs.keep_days`, default 30).

### Changed

- The app is named **Kengash AI** and installs as `kengash-ai` (PyPI refused `super-harness` as too similar to `superharness`). The `harness` and `hrn` commands, `~/.harness` and every file format stay; an `kengash_ai` command is added.
- Antigravity replaces Gemini CLI: Google moved Gemini CLI's subscription plans to Antigravity CLI, so `gemini` is no longer a provider; a setting naming it says to use `antigravity`.

### Security

- The UI checks Host, Origin, a per-run token and an `X-Harness` header on changes, and sends a strict Content Security Policy with framing, sniffing and referrer protections.

[0.2.0]: https://github.com/normatov07/kengash-ai/releases/tag/v0.2.0
[0.1.0]: https://github.com/normatov07/kengash-ai/releases/tag/v0.1.0
