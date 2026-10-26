# Contributing

Thank you for helping. This page says how to set up, what a change needs, and how it lands.

## Set up

Requires Linux or macOS, [uv](https://docs.astral.sh/uv/), git and GNU make.

    git clone https://github.com/normatov07/super-harness
    cd super-harness
    make setup      # the environment and the git hooks
    make check      # what CI runs: format, lint, types, tests, docs and skill checks

`make live` and `make evals` run the real agent CLIs and spend subscription quota; CI never runs them.

## Before you write code

- Read [AGENTS.md](AGENTS.md): its hard rules apply to people too.
- A change to a contract starts in its spec under `docs/superpowers/specs/`; the spec wins over code.
- Bigger work goes spec, then plan (`docs/superpowers/plans/`), then build, then a critical review.

## What a change needs

- Tests first: write the failing test, watch it fail, then make it pass.
- A change under `src/super_harness/<module>` updates `docs/modules/<module>/README.md` in the same commit; the pre-commit hook and CI check it.
- `make check` passes. For packaging changes, `make dist` passes too.
- Commit messages in the [Conventional Commits](https://www.conventionalcommits.org/) style (`feat:`, `fix:`, `docs:`, `build:` …), saying why as well as what.
- User-visible changes get a line under the next version in [CHANGELOG.md](CHANGELOG.md).

## Dependencies

Dependencies are locked in `uv.lock`. Dependabot opens security updates; to take routine upgrades, run `uv lock --upgrade`, then `make check` and `make audit`, and open a pull request.

## Pull requests

Keep each pull request to one purpose, fill in the template, and make sure CI is green on every job. A maintainer reviews it; expect questions about tests and the spec.

## Conduct and security

Everyone here follows the [code of conduct](CODE_OF_CONDUCT.md). Report vulnerabilities privately as [SECURITY.md](SECURITY.md) explains, never in a public issue.
