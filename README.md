# super-harness

Run many projects at once with the coding-agent subscriptions you already pay for (Claude Code, Codex, Antigravity), through their official CLIs, never API keys.

> Status: early development, sub-project 1 of 5. The `harness` CLI only prints its version so far.

## How it will work

1. `/to-plan-with-grill` or `/to-plan`: your agent turns a prompt into a reviewed plan.
2. `/to-ticket`: the plan becomes small tickets with importance, dependencies and touched paths.
3. `/to-loop`: tickets run through importance-based agent loops (plan, review, implement, review, security) in parallel across projects, each in its own git worktree, with loop caps you approve.
4. `/open-ui`: a local board shows every ticket, step, model, token count and code change.

## Develop

Requires [uv](https://docs.astral.sh/uv/) and GNU make.

    make setup   # environment and git hooks
    make check   # format, lint, types, tests, docs checks

Design: `docs/superpowers/specs/2026-10-22-super-harness-design.md`. Agent instructions: `AGENTS.md`.

## License

MIT
