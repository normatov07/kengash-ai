# Changelog

All notable changes to this project are written here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- An approved plan flows on: `/kengash:plan` and `/kengash:grill` cut the tickets as soon as you approve, with no second yes, each ticket's scope 3 to 8 lines.
- Auto mode (`loop_start: auto`, switched in Settings or on Overview): once tickets are added the loop starts by itself; with it off your agent asks once.
- One live loop per project: `kengash loop claim|release|status` keep a lease per agent session; a second loop on the same project is refused (exit 6) and told which session runs it, and `--take-over` frees a lease you know is dead. A lease ends with its session, or after an hour without a `wait`.
- A running loop starts newly ready tickets at once: `kengash wait` reports `queued` when a ticket is added ready or unblocked by a merge.
- `kengash skills show <name>` prints a skill as installed for the calling agent; skills hand over to each other through it.
- Overview names the running loop and reads again every 30 s.

### Changed

- The loop skill's event table moved to `loop/references/events.md`. Run `kengash skills install --agent … [--global]` again to get the new skills.

## [0.3.0] - 2026-10-30

### Breaking

- The `harness` and `hrn` commands, deprecated since 0.2.0, are gone; use `kengash`. `HARNESS_HOME` and `HARNESS_AGENT` are still read.
- Skills are the `kengash` plugin: `/kengash:plan`, `/kengash:grill`, `/kengash:ticket`, `/kengash:loop`, `/kengash:ui`, and `memory` loads itself; Codex, which has no plugin namespace, gets `$kengash-plan` and so on. Run `kengash skills install --agent … [--global]` again: Claude Code gets the plugin folder `.claude/skills/kengash/`, Antigravity `agy plugin install`, Codex `kengash-<name>` copies, and 0.2.0's `to-plan`, `to-plan-with-grill`, `to-ticket`, `to-loop`, `open-ui` and `kengash-memory` skills of ours are removed. `kengash doctor` points out any left behind.
- Built-in agents keep their skill: a SETTINGS.md that points one at another skill fails validation and says how to fix it, and the copies of built-in role skills `kengash init` seeded into the store are no longer read (`kengash doctor` names them). Copy the agent to change what it does.
- A send-back (`on_fail`) edge only points to an earlier step; workflow names are lowercase letters, digits, `-` and `_`; a model after `/` is one word.

### Added

- Your own agents in full, from the UI or the CLI: kind, description, CLI and model, ordered fallbacks, a skill or instructions of their own (`roles/<role>/SKILL.md`, within the skill caps), blocking and permission switches, and the workflows they run in. `kengash agent edit|copy|show`; `kengash agent new` takes `--fallback`, `--skill` and `--instructions-file`.
- Workflows you create, copy, rename and delete, and `routing`, which picks the workflow each importance gets (`kengash workflow new|rename|remove|route|set`).
- The Agents screen lists every agent beside a full editor, with drafts per agent and one Save; built-in agents show their instructions read-only and offer "Copy as my agent".
- The Workflow screen inserts any agent on any link, moves steps by drag or Alt+arrow keys, swaps a step's agent, and sets each importance's workflow and loop cap.
- Settings shows the plan reviewer, plan review rounds, grill round size, merge mode and memory compactor as real controls; model pickers list each CLI's models (agy's from `agy models`).
- Every `--project/-p` option takes a project name or a folder inside a registered repo; a folder no project holds exits 4 naming `kengash init`.
- The planning, ticket and loop skills take an optional project name or folder after their argument; an unregistered folder is registered only on your yes.
- Board cards show up to three tags.

### Fixed

- Every screen works from 360 px up: the sidebar folds into a menu below 900 px, the roster no longer overlaps, the workflow graph pans inside its stage, the ticket index keeps its title column, and closed choices are selects or radio cards instead of text boxes.
- `kengash agent new --help` crashed on Rich markup in its help text.
- `kengash agent new` with a review step placed before `implement` defaulted to a send-back to `implement`, which points forward; it now adds no edge there.
- The Workflow screen's send-back select shared its id with the graph's arrow marker.
- `kengash wait` could answer `idle` while a finishing worker journaled its gate, so the loop ended without asking for the merge; it now checks running work, live workers included, before reading the journal.
- `make lint` and `make evals` ran the deprecated `harness` command; the demo store, the view benchmark and the live smoke still used 0.1.0 names.
- CI: a hung test could sit silent until the 20-minute job limit; each test now stops after 300 s with every thread's stack, `make check`'s stages run as separate CI steps, and a test no longer leaves its SIGALRM handler behind.

## [0.2.0] - 2026-10-26

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

[0.3.0]: https://github.com/normatov07/kengash-ai/releases/tag/v0.3.0
[0.2.0]: https://github.com/normatov07/kengash-ai/releases/tag/v0.2.0
[0.1.0]: https://github.com/normatov07/kengash-ai/releases/tag/v0.1.0
