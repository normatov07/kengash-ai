# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

Design written; implementation not started. There are no build, lint or test commands yet; do not invent them. Sub-project 1 (Foundation) adds them and moves this file's content into `AGENTS.md`, leaving only an `@AGENTS.md` import here.

- Design spec (system contracts and Foundation): `docs/superpowers/specs/2026-10-22-super-harness-design.md`. Read the section that covers what you are changing. Where it differs from `full prompt of app.md` (the user's original prompt), the spec wins.
- Process per sub-project: spec → plan in `docs/superpowers/plans/` → build → critical review against the requirements. Order: 1 Foundation, 2 Store + `harness` CLI, 3 Engine, 4 Skills, 5 Web UI.

## What super-harness is

An open-source Python harness that lets one developer run many projects at once using only subscription coding-agent CLIs (Claude Code, Codex, Antigravity `agy`; Gemini CLI optional), never API keys. Skills installed into the user's agent conduct the loop, a deterministic `harness` CLI does every mechanical step, and a local UI monitors everything.

## Hard rules

- Each project links to the store through one directory symlink, `<repo>/.harness -> ~/.harness/projects/<slug>`. Never use hard links.
- Only `harness` writes store files; agents never hand-edit plan or ticket state.
- Tickets reference their plan by id; never copy the full prompt into tickets.
- Drive providers only through their official binaries under the user's login. Never read or reuse OAuth tokens, never use `claude --bare` (it skips subscription login), and strip provider API-key variables from worker environments.
- No always-on daemon: workers are short-lived detached processes, one per job.

## UI design source

The UI must implement the Claude Design canvas https://claude.ai/artifact/JiMGMkbaw8qhafeaNbqU7d. Read it with the Artifact tool (`list_files`, then `read_file` on `project/canvas.json` and `project/*.dc.html`), not WebFetch or DesignSync.
