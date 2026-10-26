# super-harness

[![ci](https://github.com/normatov07/super-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/normatov07/super-harness/actions/workflows/ci.yml)

Run many projects at once with the coding-agent subscriptions you already pay for (Claude Code, Codex, Antigravity), through their official CLIs, never API keys.

You talk to your usual agent. Skills installed into it turn a prompt into a reviewed plan and small tickets, then run each ticket through an agent loop sized to its importance (plan, review, implement, review, security), in parallel across projects, each ticket in its own git worktree. A deterministic `harness` CLI does every mechanical step, a shared memory store keeps decisions across sessions, and a local web UI shows and steers it all.

## Features

- **Subscriptions, not API keys.** Drives `claude`, `codex` and `agy` headless under your own login, reuses one CLI session per ticket and role, and strips provider API-key variables from every worker.
- **Importance-based loops.** Simple, standard and critical workflows with loop caps, token caps, stall detection and send-back edges; you approve extra loops.
- **Parallel and safe.** Tickets that touch the same paths run one at a time; the rest run side by side, each in its own worktree, merged when you say so.
- **Your own agents.** Add a role and its step (`read`, `edit` or `review`) from the CLI or the UI, with a starter skill you can edit.
- **Memory that lasts.** One store at `~/.harness`, linked into every project by a folder link: MEMORY.md and DECISIONS.md for all projects, PROCESS.md and SETTINGS.md per project, compacted when they grow.
- **A local control room.** Overview, task board, ticket sheets with every change, a workflow editor, agents and providers, settings and memory, live over server-sent events.

## Requirements

- Linux or macOS (on Windows, use WSL), Python 3.12 or newer, git.
- [uv](https://docs.astral.sh/uv/) to install.
- At least one signed-in agent CLI: Claude Code (`claude`), Codex (`codex`) or Antigravity (`agy`).

## Install

    uv tool install 'super-harness[ui] @ git+https://github.com/normatov07/super-harness'
    harness skills install --agent claude,codex,antigravity --global
    harness doctor

Once a release is on PyPI: `uv tool install 'super-harness[ui]'` or `pipx install 'super-harness[ui]'`. Leave out `[ui]` for the CLI alone.

The skills can also come from Claude Code's plugin marketplace (`/plugin install super-harness --marketplace normatov07/super-harness`) or `npx skills add normatov07/super-harness`.

## Quick start

    cd ~/code/my-app
    harness init            # registers the project and links .harness to the store

Then, in your agent:

1. `/to-plan` (or `/to-plan-with-grill` to be interviewed first): a plan, reviewed by an agent on another provider.
2. `/to-ticket`: the plan becomes tickets with importance, dependencies and touched paths.
3. `/to-loop`: tickets run in their loops; the agent waits, reports gates and asks before granting loops or merging.
4. `/open-ui` (or `harness ui open`): the web UI on 127.0.0.1 behind a private link.

## Commands

| Command | Does |
|---|---|
| `harness init`, `link`, `adopt`, `doctor [--fix]` | register projects, repair links, check everything |
| `harness plan …`, `ticket …` | plans and tickets (agents use these; they never edit store files) |
| `harness next`, `run`, `wait`, `status` | what can start, start it, wait for gates, a summary |
| `harness approve`, `park`, `stop`, `pause`, `resume`, `merge` | steer running work |
| `harness settings show\|get\|check`, `memory …`, `context` | settings, memory and the conductor's digest |
| `harness agent new\|remove` | your own roles and steps |
| `harness skills install\|lint\|eval`, `ui open\|stop` | skills and the web UI |

Every command takes `--help`, and most take `--json`. Exit codes: 0 done, 1 a problem, 3 timed out, 4 setup needed, 5 your decision needed.

## Configuration

Settings live in SETTINGS.md files: the package defaults, then `~/.harness/defaults/SETTINGS.md`, then each project's own copy (written by `harness init` and never overwritten). Edit them in the UI's Settings, Workflow and Agents screens, which change only the lines you touch, or by hand and check them with `harness settings check`. Common keys:

    loop_max.critical: 6
    agents:
      implementer: {on: true, cli: codex, skill: implement, fallback: [claude/sonnet]}
    sessions.per_provider: {claude: 3, codex: 3, antigravity: 2}
    logs.keep_days: 30      # worker logs untouched this long are removed; 0 keeps all

Add your own agent to a workflow, for example a performance reviewer that sends failing work back:

    harness agent new perf-reviewer --kind review --does "Flag N+1 queries and hot loops." \
        --cli claude/sonnet --workflow critical --after review_code

## Security model

- Providers run only through their official binaries under your login; harness never reads or reuses OAuth tokens and removes provider API-key variables from worker environments.
- The UI binds to 127.0.0.1, checks Host and Origin, needs a fresh per-run token (kept in an `HttpOnly`, `SameSite=Strict` cookie), requires an `X-Harness` header on every change, and sends a strict Content Security Policy.
- The store is a private git repository; text written to memory, tickets and the journal is redacted for common secret shapes.
- Workers are short-lived processes, one per job; nothing runs in the background between jobs.

Report vulnerabilities privately: see [SECURITY.md](SECURITY.md).

## Troubleshooting

- `harness doctor` names each problem and its fix; `harness doctor --fix` repairs links, exclude entries and dead workers, and prunes old logs.
- A provider shows "signed out": run the sign-in command the Agents screen or `doctor` prints, then "Check sign-in again".
- A ticket is stalled or at a loop cap: open it on the board; the sheet shows the findings and the approve or park actions.
- Worker logs are in `~/.harness/runtime/logs/`.

## Uninstall

    harness ui stop
    uv tool uninstall super-harness

Your store stays in `~/.harness`; remove it and each project's `.harness` link by hand if you want them gone.

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
