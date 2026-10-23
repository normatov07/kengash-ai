# super-harness

Run many projects at once with the coding-agent subscriptions you already pay for (Claude Code, Codex, Antigravity), through their official CLIs, never API keys.

> Status: early development, sub-projects 1–4 of 5 done (foundation, store and CLI, engine, skills). The local web UI is next.

## How it works

1. `/to-plan-with-grill` or `/to-plan`: your agent turns a prompt into a plan that an agent on another provider reviews.
2. `/to-ticket`: the plan becomes small tickets with importance, dependencies and touched paths.
3. `/to-loop`: tickets run through importance-based agent loops (plan, review, implement, review, security) in parallel across projects, each in its own git worktree, with loop caps you approve.
4. `harness-memory`: lasting preferences and decisions are kept for every agent and session.
5. Coming with the UI: `/open-ui`, a local board of every ticket, step, model, token count and code change.

## Install

Requires [uv](https://docs.astral.sh/uv/) and at least one signed-in agent CLI (`claude`, `codex` or `agy`).

    uv tool install git+https://github.com/normatov07/super-harness
    harness skills install --agent claude,codex,antigravity --global
    harness doctor

Or add the skills another way:

- Claude Code: `/plugin install super-harness --marketplace normatov07/super-harness`
- Any agent: `npx skills add normatov07/super-harness`

Then run `harness init` inside each project.

## Develop

Requires uv and GNU make.

    make setup   # environment and git hooks
    make check   # format, lint, types, tests, docs and skill checks
    make live    # live smoke on the real CLIs (spends quota)
    make evals   # skill evals on the real CLIs (spends quota)

Design: `docs/superpowers/specs/2026-10-22-super-harness-design.md`. Agent instructions: `AGENTS.md`.

## License

MIT
