# AGENTS.md

super-harness lets one developer run many projects at once with the coding-agent subscriptions they already have (Claude Code, Codex, Antigravity `agy`; Gemini CLI optional), driven through the official CLIs, never API keys. Skills installed into the user's agent conduct the work, the deterministic `harness` CLI does every mechanical step, and a local UI monitors it all.

Status: all 5 sub-projects done (Foundation; Store + `harness` CLI; Engine; Skills; Web UI): `harness init|doctor|link|adopt|settings|memory|context|plan|ticket|status|next|run|wait|approve|park|stop|pause|resume|merge|skills|ui` work, with detached workers, plan review, memory compaction, role skills, six installed skills (`skills/`, proven by `evals/`), and the local web UI (`harness ui open`, seven screens matching the canvas). `docs/architecture.md` tracks what is built.

## Commands

- `make setup`: install the uv environment and git hooks
- `make check`: everything CI runs (format, lint, types, tests, docs checks)
- `make fmt`: format and auto-fix
- `make live`: live smoke on the real provider CLIs (spends subscription quota; never in `make check`)
- `make evals`: every skill scenario on every installed agent (spends quota; never in `make check`)
- One test: `uv run pytest tests/test_cli.py::test_version_names_the_package`
- `make docs DOCS_BASE=origin/main`: docs checks against another base

## Hard rules

1. The spec `docs/superpowers/specs/2026-10-22-super-harness-design.md` is the contract. Where it differs from `full prompt of app.md` (the original request), the spec wins. Change the spec before changing a contract.
2. A change to `src/super_harness/<module>` updates `docs/modules/<module>/README.md` in the same commit; `make docs` and the pre-commit hook enforce it.
3. Each project links to the store through one directory symlink. Never use hard links: they cannot link directories and break on status-folder moves and atomic saves.
4. Only `harness` writes store files; agents never hand-edit plan or ticket state.
5. Tickets reference their plan by id; never copy the full prompt into tickets.
6. Providers run only through their official binaries under the user's login: never read or reuse OAuth tokens, never use `claude --bare` (it skips subscription login), and strip provider API-key variables from worker environments.
7. No always-on daemon: workers are short-lived detached processes, one per job.
8. Instruction files stay within caps: this file ≤ 100 lines, files under `docs/` ≤ 150 lines (specs and plans exempt).
9. Each sub-project goes spec → plan → build → critical review of every change against the requirements before the next one starts.

## Read when

- `docs/architecture.md`: adding or moving a module, or changing module dependencies
- `docs/conventions/instruction-files.md`: writing AGENTS.md, CLAUDE.md, GEMINI.md or any doc
- `docs/conventions/skills.md`: writing a skill or role skill
- `docs/conventions/memory-files.md`: touching MEMORY.md, DECISIONS.md, PROCESS.md, SETTINGS.md, plan or ticket formats
- `docs/modules/<module>/README.md`: changing that module
- `docs/superpowers/plans/`: implementing a sub-project step by step

## UI design source

The UI implements the Claude Design canvas https://claude.ai/artifact/JiMGMkbaw8qhafeaNbqU7d. In Claude Code, read it with the Artifact tool (`list_files`, then `read_file` on `project/canvas.json` and `project/*.dc.html`), not WebFetch.
