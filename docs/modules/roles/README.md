# roles

## Purpose

Role skills, data only (system spec §8.2; SP4 spec decision 3): the instructions a worker session gets for its step. `plan`, `review-plan`, `implement`, `review-code`, `review-security`, `run-tests`, `sync-docs`, each `roles/<role>/SKILL.md` with Agent Skills frontmatter (`name`, `description`, `metadata: {source: kengash-ai}`).

## Interface

- A new session gets the body, without its frontmatter: claude through `--append-system-prompt`, other CLIs prepended to the prompt (`ops.prompts.role_skill`).
- Lookup: `projects/<slug>/roles/<role>/SKILL.md` → `defaults/roles/<role>/SKILL.md` → the package (`ops.skills.role_text`).
- `harness init` seeds every package role missing from `defaults/roles/` and never overwrites one (`store.seed`).

## Invariants

- Never installed into agents; only workers read them.
- Each stays within the skill caps (80 lines, 400 words) and ends on the JSON reply its step's schema expects.
- `name` equals the folder.

## Changes

- 2026-10-26: the package is `kengash_ai` (the app is Kengash AI, distributed as `kengash-ai`; SP7 spec decision 16).
- 2026-10-23: the seven role skills (SP4 M1).
