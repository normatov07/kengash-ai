# Kengash AI

[![ci](https://github.com/normatov07/kengash-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/normatov07/kengash-ai/actions/workflows/ci.yml)

A council of coding agents (*kengash* is Uzbek for council) that works many projects at once with the subscriptions you already pay for (Claude Code, Codex, Antigravity), through their official CLIs, never API keys.

You talk to your usual agent. Skills installed into it turn a prompt into a reviewed plan and small tickets, then run each ticket through an agent loop sized to its importance (plan, review, implement, review, security), in parallel across projects, each ticket in its own git worktree. A deterministic `kengash` CLI does every mechanical step, a shared memory store keeps decisions across sessions, and a local web UI shows and steers it all.

## Features

- **Subscriptions, not API keys.** Drives `claude`, `codex` and `agy` headless under your own login, reuses one CLI session per ticket and role, and strips provider API-key variables from every worker.
- **Importance-based loops.** Simple, standard and critical workflows with loop caps, token caps, stall detection and send-back edges; you approve extra loops.
- **Parallel and safe.** Tickets that touch the same paths run one at a time; the rest run side by side, each in its own worktree, merged when you say so.
- **Your own agents.** Add a role and its step (`read`, `edit` or `review`) from the CLI or the UI, with a starter skill you can edit.
- **Memory that lasts.** One store at `~/.kengash`, linked into every project by a folder link: MEMORY.md and DECISIONS.md for all projects, PROCESS.md and SETTINGS.md per project, compacted when they grow.
- **A local control room.** Overview, task board, ticket sheets with every change, a workflow editor, agents and providers, settings and memory, live over server-sent events.

## Requirements

- Linux or macOS (on Windows, use WSL), Python 3.12 or newer, git.
- [uv](https://docs.astral.sh/uv/) to install.
- At least one signed-in agent CLI: Claude Code (`claude`), Codex (`codex`) or Antigravity (`agy`).

## Install

    uv tool install 'kengash-ai[ui]'        # or: pipx install 'kengash-ai[ui]'
    kengash skills install --agent claude,codex,antigravity --global
    kengash doctor

Leave out `[ui]` for the CLI alone. The latest code: `uv tool install 'kengash-ai[ui] @ git+https://github.com/normatov07/kengash-ai'`.

### Upgrading from 0.1.0

`uv tool upgrade kengash-ai`, then run any `kengash` command once: it moves `~/.harness` to `~/.kengash` and leaves a link behind, so nothing in flight breaks. Then `kengash skills install --agent … --global` (it replaces `harness-memory` with `kengash-memory`) and `kengash doctor --fix` (it turns each project's `.harness` link into `.kengash`). The `harness` and `hrn` commands keep working with a warning until 0.3.0. If your agent's permissions allow `Bash(harness:*)`, allow `Bash(kengash:*)` too.

The skills install as the `kengash` plugin: in Claude Code and Antigravity you type `/kengash:plan`, `/kengash:grill`, `/kengash:ticket`, `/kengash:loop` and `/kengash:ui`; Codex has no plugin namespace, so it gets `$kengash-plan` and so on. Claude Code can also take the plugin from its marketplace: `/plugin marketplace add normatov07/kengash-ai`, then `/plugin install kengash@kengash-ai`.

### Upgrading from 0.2.0

Run `kengash skills install --agent … --global` again: the commands are now `/kengash:<name>`, and the old `to-plan`, `to-plan-with-grill`, `to-ticket`, `to-loop`, `open-ui` and `kengash-memory` skills of ours are removed (`kengash doctor` points out any left behind).

## Quick start

    cd ~/code/my-app
    kengash init            # registers the project and links .kengash to the store

Then, in your agent:

1. `/kengash:plan` (or `/kengash:grill` to be interviewed first): a plan, reviewed by an agent on another provider.
2. `/kengash:ticket`: the plan becomes tickets with importance, dependencies and touched paths.
3. `/kengash:loop`: tickets run in their loops; the agent waits, reports gates and asks before granting loops or merging.
4. `/kengash:ui` (or `kengash ui open`): the web UI on 127.0.0.1 behind a private link.

The first three take an optional project name or folder at the end, such as `/kengash:loop payments-api` or `/kengash:ticket "<prompt>" ~/code/payments`; without one, planning uses the project you are in and `/kengash:loop` works every project. Every `--project/-p` option of `kengash` takes a name or a folder too. In Codex, type `$kengash-loop` and so on.

## Commands

| Command | Does |
|---|---|
| `kengash init`, `link`, `adopt`, `doctor [--fix]` | register projects, repair links, check everything |
| `kengash plan …`, `ticket …` | plans and tickets (agents use these; they never edit store files) |
| `kengash next`, `run`, `wait`, `status` | what can start, start it, wait for gates, a summary |
| `kengash approve`, `park`, `stop`, `pause`, `resume`, `merge` | steer running work |
| `kengash settings show\|get\|check`, `memory …`, `context` | settings, memory and the conductor's digest |
| `kengash agent new\|remove` | your own roles and steps |
| `kengash skills install\|lint\|eval`, `ui open\|stop` | skills and the web UI |

Every command takes `--help`, and most take `--json`. Exit codes: 0 done, 1 a problem, 3 timed out, 4 setup needed, 5 your decision needed.

## Configuration

Settings live in SETTINGS.md files: the package defaults, then `~/.kengash/defaults/SETTINGS.md`, then each project's own copy (written by `kengash init` and never overwritten). Edit them in the UI's Settings, Workflow and Agents screens, which change only the lines you touch, or by hand and check them with `kengash settings check`. Common keys:

    loop_max.critical: 6
    agents:
      implementer: {on: true, cli: codex, skill: implement, fallback: [claude/sonnet]}
    sessions.per_provider: {claude: 3, codex: 3, antigravity: 2}
    logs.keep_days: 30      # worker logs untouched this long are removed; 0 keeps all

Add your own agent to a workflow, for example a performance reviewer that sends failing work back:

    kengash agent new perf-reviewer --kind review --does "Flag N+1 queries and hot loops." \
        --cli claude/sonnet --workflow critical --after review_code

## Security model

- Providers run only through their official binaries under your login; kengash never reads or reuses OAuth tokens and removes provider API-key variables from worker environments.
- The UI binds to 127.0.0.1, checks Host and Origin, needs a fresh per-run token (kept in an `HttpOnly`, `SameSite=Strict` cookie), requires an `X-Harness` header on every change, and sends a strict Content Security Policy.
- The store is a private git repository; text written to memory, tickets and the journal is redacted for common secret shapes.
- Workers are short-lived processes, one per job; nothing runs in the background between jobs.

Report vulnerabilities privately: see [SECURITY.md](SECURITY.md).

## Troubleshooting

- `kengash doctor` names each problem and its fix; `kengash doctor --fix` repairs links, exclude entries and dead workers, and prunes old logs.
- A provider shows "signed out": run the sign-in command the Agents screen or `doctor` prints, then "Check sign-in again".
- A ticket is stalled or at a loop cap: open it on the board; the sheet shows the findings and the approve or park actions.
- Worker logs are in `~/.kengash/runtime/logs/`.

## Uninstall

    kengash ui stop
    uv tool uninstall kengash-ai

Your store stays in `~/.kengash`; remove it and each project's `.kengash` link by hand if you want them gone.

## Develop

Requires uv and GNU make. See [CONTRIBUTING.md](CONTRIBUTING.md).

    make setup   # environment and git hooks
    make check   # format, lint, types, tests, docs and skill checks
    make dist    # build and check the release artifacts
    make audit   # known vulnerabilities in the locked dependencies
    make live    # live smoke on the real CLIs (spends quota)
    make evals   # skill evals on the real CLIs (spends quota)

Design: [docs/superpowers/specs/](docs/superpowers/specs/). Agent instructions: [AGENTS.md](AGENTS.md). Changes: [CHANGELOG.md](CHANGELOG.md).

## License

MIT
