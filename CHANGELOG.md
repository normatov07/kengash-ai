# Changelog

All notable changes to this project are written here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Automatic memory: a one-shot job on the cheap model records what you settle, at `plan approve`, `plan reject --why`, `approve --note`, and when a Claude Code session compacts or ends (`kengash skills install --global` adds those two hooks to `~/.claude/settings.json`). A fact must quote your own words or it is dropped, and only registered projects are read. `memory.harvest` is `all`, `plans` or `off`; `kengash memory forget "<words>"` removes a line; `kengash memory harvest --plan <id>` reads a plan approved earlier.
- `kengash ticket add --check` reports a ticket list's levels, chokepoints, files that force tickets to run one at a time, top-level folders claimed, and files many past tickets changed. It creates nothing.
- Merge conflicts are settled inside the ticket. A failed rebase is replayed as one change on the base with conflict markers in the clashing files, and the implementer only edits files; markers can never be committed. Up to `merge.conflict_turns` (default 2) cost no loop.
- `project.generate_cmd` rebuilds generated files before kengash's checks, and a conflict only in generated files lands with no worker. `project.commands` lists more commands workers may run.
- `kengash next` and `kengash watch` say when a ticket at a gate or parked holds three or more others back.
- Steering: a CLI call that polls a background command, reruns the whole test suite or passes its soft deadline is stopped and resumed with a correction, up to `steering.turns` times, then goes to the fallback chain. The work stays in the worktree.
- The relay: while a loop is on, a finishing worker, a merge, an approval or a resume starts what is now runnable, so no conductor has to be awake. No process stays behind. It stops after 24 hours without starting anything, `kengash loop status` shows what it covers, and `loop_relay: false` turns it off for a project.
- A plan over `plan.max_files` (default 12) can split its ticket into parts. A split that loses an acceptance line is refused and the ticket continues whole.
- New editing sessions get the plan's files inline, read at that moment (`context.max_kib`); a resumed session is told which files changed since it last spoke; a memory line naming a file that is gone is tagged, not hidden.
- A model per ticket importance on every agent (Agents page, or `kengash agent edit --model-for critical=claude/opus`), and "Other models" for the plan reviewer and the memory compactor.
- `checks.parallel` limits kengash's own test runs on this machine (default: half the CPU cores).

### Changed

- `tokens.per_ticket_max` defaults to 3,000,000; `kengash doctor --fix` updates the old 1,000,000.
- A branch whose base moved is rebased before review when that applies cleanly.
- Every `depends_on` in `ticket add` needs a `needs` line saying what it uses from that ticket.
- `plan save` of a full plan needs a `## Lasting decisions` section; `none` is allowed.
- Workers get your decisions first, then those naming the ticket's paths, and more of them fit.
- A claim on a whole test folder no longer makes tickets wait; files an editing step changes outside its claim join the claim.

### Fixed

- A cheap conductor sometimes tried the Skill tool at the plan-to-ticket handoff, was refused and stopped; the skills now say it is a shell command.
- A compaction whose result drops a pinned line gets one repair turn before kengash refuses it.

### Changed

- Two editing tickets may share up to `paths.max_overlap` exact files (default 2), and generated files (`paths.shared`) never count. A real conflict surfaces at the rebase; `paths.max_overlap: 0` restores the old behaviour.
- A review fails only on `review.block_on` (default high and medium). A finding naming no real file or line is demoted to low.
- New stores run the code reviewer on Sonnet, with Opus for `critical` tickets. Existing settings are never overwritten.
- A hard timeout resumes the session with a correction instead of repeating the prompt; a crash retries once after 20 seconds, then uses the fallback chain.
- A timed-out or stopped call reports its session and the tokens its stream shows, so the token cap sees that spend. Claude's stream holds only each message's opening output count, so a stopped Claude call's output tokens are a floor (input and cache are exact), and Codex reports usage only when a turn ends, so a stopped Codex call counts none.

## [0.6.0] - 2026-11-07

### Added

- Checks inside editing steps: after an implement step, kengash runs the project's `test_cmd` and `lint_cmd` in the worktree. While they fail, it resumes the same session with the failure, up to `checks.turns` times (default 2; 0 turns it off). `run_tests` reuses a pass on the same commit.
- Failures agents can act on: a failing check writes a digest (headline, file and line, a fenced excerpt) to Findings and a new `## Check output` section. Prompts name the checks and say which step sent the work back and why. agy implementers may now run the project's test and lint commands.
- A handoff line `BLOCKED: <what>` stops a ticket at `needs_approval` for what only you can give; `kengash approve <id> --note "<answer>"` hands your answer to the next step.
- Every new worker session starts with a `## Memory` block: the project's PROCESS.md notes, its and the global decisions, and your preferences, each capped, newest winning.
- Decisions are recorded without anyone remembering to. A plan's `## Lasting decisions` reach DECISIONS.md when you approve it. Workers propose `decisions` in their replies; the code reviewer can strike any that is not a lasting choice, and the rest land in DECISIONS.md when the ticket merges.
- `kengash memory add --process` appends a process note to the project's PROCESS.md, and `kengash context` ends with a `# Record` hint saying what goes where. Near-duplicate memory lines count as already recorded.
- Tickets run in parallel:
  - planning steps neither hold nor check paths, so overlapping tickets plan at once;
  - a planner's `files` narrow the ticket's `touches` to the exact files;
  - only tickets that are editing hold their paths; one that would edit the same files waits as `waiting_paths` and goes on when they are free;
  - the ready ticket with the longest chain of waiting dependents starts first;
  - an edit starts from the newest main when the branch has no work yet;
  - the ticket skill keeps `depends_on` and `touches` minimal.
- A merge queue: merges of one project take turns, and a ticket whose rebase moved onto a newer main reruns the checks before main moves; a failure goes back to implement with the check output.

### Changed

- `merge.mode` defaults to `auto`: a green ticket merges into your local main by itself (kengash never pushes), after a recheck unless its checks passed on that exact commit. It asks you only when the merge cannot finish (for example, uncommitted changes in the main working tree), and says why. Stores seeded before 0.6.0 keep the `merge.mode: ask` they were written with.
- Read steps reply with the new `plan` output (`files`, `decisions`), and work replies carry `decisions`; both may be empty lists.

### Fixed

- After an upgrade, a UI server started by the old version showed `damaged runtime file (Extra inputs are not permitted)` for tickets the new version had touched. Runtime files now ignore fields they do not know, and `kengash ui open` replaces a server started by another version.
- An agy step cut by a dropped connection (`cannot rewind body after connection loss`) failed the ticket as a crash; it now counts as a network error, so the step resumes once and then uses the fallback.

## [0.5.0] - 2026-11-07

### Added

- `kengash forget <project> [--yes]` removes a project kengash should no longer know: its plans, tickets, worktrees and `.kengash` link. The store's git history keeps every removed store file; uncommitted changes in a ticket's worktree are lost, and it says how many worktrees hold some before asking. `kengash doctor` names it for a repo that is gone.

### Fixed

- A git worktree of a registered repo, such as an Orca workspace, belongs to that repo's project: commands run inside it work on the project, and `kengash init` there no longer registers a second project.
- `kengash doctor` names a workflow whose `run_tests` runs after the code review or has no way back to `implement` (a failing test then failed the ticket), and `doctor --fix` moves it right after `implement` and routes failures back to it.

## [0.4.0] - 2026-11-07

### Added

- An approved plan flows on: `/kengash:plan` and `/kengash:grill` cut the tickets as soon as you approve, with no second yes, each ticket's scope 3 to 8 lines.
- Auto mode (`loop_start: auto`, switched in Settings or on Overview): once tickets are added the loop starts by itself; with it off your agent asks once.
- One live loop per project: `kengash loop claim|release|status` keep a lease per agent session; a second loop on the same project is refused (exit 6) and told which session runs it, and `--take-over` frees a lease you know is dead. A lease ends with its session, or after an hour without a `wait`.
- A running loop starts newly ready tickets at once: `kengash wait` reports `queued` when a ticket is added ready or unblocked by a merge.
- `kengash skills show <name>` prints a skill as installed for the calling agent; skills hand over to each other through it.
- Overview names the running loop and reads again every 30 s.

- Finished work survives a dropped connection: a worker CLI that returned a valid result and then lost its connection counts as done; a network error resumes the session once ("your edits are kept"), then hands the step to the agent's fallback.
- Watch your workers: `kengash wait` prints a progress line per running worker every 5 minutes (step, CLI and model, elapsed, last activity, changed files, last action); `kengash ps [--line]`; `kengash logs <id> [-f]` follows a worker's reads, edits, commands and replies; the UI's ticket sheet has a Live tab, Overview rows show the last activity and running cards pulse.
- `kengash init` detects test and lint commands (Flutter, Dart, uv, Node, Go, Rust) and adds a `run_tests` step that runs both after `implement`; `kengash doctor` names projects without them, settings still at an old default, and agents without a fallback, and `doctor --fix` repairs the first two.

- Watch every worker: starting a ticket's worker opens a terminal tab (`kg <id>`) that follows it through its gates until it is done (`kengash logs <id> --watch`), and a new loop opens a dashboard tab, in Orca, tmux or gnome-terminal, or the command in `watch.terminal`; at most one tab per ticket, and `run`, `approve` and `loop claim` say where to watch.
- `kengash watch [-p project] [--once]`: one live screen with the running loops, sessions and tokens per CLI, every running worker (step, model, elapsed, last activity, files, tokens of its cap, last action), the tickets that need you with the command that acts, and the latest actions across all workers. Nothing in it runs a model.
- A desktop notification (`notify-send`, or `osascript` on macOS) when a ticket needs approval, stalls, fails or is ready to merge, and when a plan review finishes (`watch.notify`).
- `kengash ticket attach <id> --tab` opens a role's own session in a tab once no worker drives it, so you can talk to that agent directly.

### Changed

- `fallback_on_rate_limit` is now `fallback_on_error` (rate limits and network errors); the old key is still read, and `kengash doctor --fix` renames it.
- The default token cap per ticket is 1,000,000 (was 250,000); `kengash doctor --fix` updates a store still at the old value.
- Failures are one line naming the log and, for an editing step, the worktree and its changed files; a failed call keeps its session, so a retry resumes it.
- Claude and Antigravity workers run with `--output-format stream-json`.
- The loop skill's event table moved to `loop/references/events.md`. Run `kengash skills install --agent … [--global]` again to get the new skills.
- With no terminal to open a tab in, `run` prints `(watch: kengash logs <id> -f)`; the loop skill starts that in the background only then, and repeats progress lines only when a worker is `quiet` or gone, which saves the conductor's tokens.
- `KENGASH_WATCH=off` turns tabs and notifications off; tests and evals set it.

### Fixed

- A worker CLI that stops without a result is no longer judged by its model's own words (a reply mentioning a quota or a dropped connection); only what the CLI itself said counts.
- `kengash logs` and the Live tab say `earlier actions omitted; full log: <log>` when a long log is read from its end.
- The Live tab's elapsed time counts on; a worker between CLI calls shows `(between calls)` there and in `kengash ps`, instead of `step→/`.
- `kengash doctor --fix` renames `fallback_on_rate_limit` where it stands, keeping its comment.
- A commit hook that fails twice names the work kept in the worktree and keeps the step's session, so `kengash run` resumes it.
- Screen readers announce a running worker on board cards and the Live tab.
- `kengash logs` and the Live tab name each step's CLI and model (`implement → antigravity/flash`).
- `kengash memory compact` or `kengash plan review` run right after the previous one ended no longer fails with `worker died`.

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

[0.6.0]: https://github.com/normatov07/kengash-ai/releases/tag/v0.6.0
[0.5.0]: https://github.com/normatov07/kengash-ai/releases/tag/v0.5.0
[0.4.0]: https://github.com/normatov07/kengash-ai/releases/tag/v0.4.0
[0.3.0]: https://github.com/normatov07/kengash-ai/releases/tag/v0.3.0
[0.2.0]: https://github.com/normatov07/kengash-ai/releases/tag/v0.2.0
[0.1.0]: https://github.com/normatov07/kengash-ai/releases/tag/v0.1.0
