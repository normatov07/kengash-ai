# Writing instruction files

How to write the files agents read: `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` and everything under `docs/`. Read this before adding or editing any of them.

## Layers

1. **Entry file** `AGENTS.md`: what the project is, the commands, at most 15 hard rules, and "Read when" links. Every agent loads it in every session, so each line costs tokens every time.
2. **Topic docs** under `docs/`: one subject each, loaded only when a "Read when" trigger fires.
3. **Code layer**: types, docstrings and config comments. Agents see these while reading code; never repeat them in docs.

## Caps

`scripts/check_md_caps.py` enforces these through `make docs` and the pre-commit hook:

| File | Cap |
|---|---|
| `AGENTS.md` | 100 lines |
| `docs/**/*.md` | 150 lines; aim for 50–150 for topic docs |
| `docs/superpowers/**` | exempt (specs and plans) |

When a doc reaches its cap, split it by subject and link the parts; never raise the cap.

## Pointer files

- `CLAUDE.md`: the `/init` prefix plus `@AGENTS.md`, which Claude Code imports.
- `GEMINI.md`: `@AGENTS.md`, which Gemini CLI imports.
- Codex and Antigravity `agy` read `AGENTS.md` directly (see `docs/architecture.md`, Agent context files).

Pointer files hold no content of their own; put it in `AGENTS.md` or a topic doc.

## Writing rules

1. Every link says what it holds and when to read it, trigger word first: "`docs/conventions/skills.md`: writing a skill".
2. Every rule that is not obvious says why and when it applies. Delete it when the why expires.
3. Phrase instructions positively: say what to do.
4. Give the shape of an output as a template. Keep "never" for discipline rules an agent might skip under pressure, and put the reason next to it.
5. Put the most important rules at the top or the bottom; the middle of a long file gets the least attention.
6. Keep one source of truth: link to it instead of copying, and never restate what code or config already says.
7. Commands you reference are quiet on success and print only failures, so agents see signal, not noise.
8. Prune on every edit: delete stale lines and lines that change nothing.

## Module docs

Every module under `src/super_harness/` has `docs/modules/<module>/README.md` with four sections:

- **Purpose**: one or two sentences.
- **Interface**: what users and other modules call.
- **Invariants**: what must stay true.
- **Changes**: newest first, at most 20 lines; older history lives in git.

The doc changes in the same commit as the module. `scripts/check_docs_sync.py` enforces this: `make docs` checks the range `DOCS_BASE...HEAD`, the pre-commit hook checks staged files. A top-level `.py` file counts as a module; package dunder files such as `__init__.py` do not.

## Who reads and writes what

| File | Read by | Written by |
|---|---|---|
| `AGENTS.md` | every agent, every session | humans and agents, reviewed in pull requests |
| `docs/modules/*` | agents changing that module | whoever changes the module |
| `docs/conventions/*` | anyone writing that kind of file | humans |
| `docs/superpowers/specs/`, `plans/` | anyone working on that sub-project | the brainstorming and writing-plans workflows |

Sources: walkinglabs learn-harness-engineering, lecture 4; HumanLayer, "Skill issue: harness engineering for coding agents"; Matt Pocock, `writing-for-agents`.
