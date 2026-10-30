# Writing skills

Rules for installable skills (`skills/<name>/SKILL.md`) and role skills (`src/kengash_ai/roles/<role>/SKILL.md`). Both arrive in sub-project 4; these rules are the contract it implements.

## Format

Skills follow the Agent Skills specification (agentskills.io):

- The folder name equals `name`: lowercase letters, digits and single hyphens, at most 64 characters.
- `description` may hold 1024 characters by spec; keep it within 500 here.
- Optional folders: `scripts/` (executables), `references/` (docs loaded on demand), `assets/` (templates, data).

## Description

- Starts with "Use when" and lists triggers only: situations, symptoms, keywords.
- Never summarises the steps: agents that read a summarised workflow tend to follow the summary and skip the body.
- Written in the third person, because it is injected into the system prompt.

## Size

| Limit | Value | Setting |
|---|---|---|
| Lines | 80 | `skill.max_lines` |
| Words | 400 | `skill.max_words` |
| Target | 200 words | — |

An installed skill's name and description load into every session of every agent it is installed in; keep both short.

## Body

- Numbered steps. Each step is one `kengash …` command or one judgment, and ends on a checkable condition, e.g. "`kengash plan show <id>` prints `status: approved`".
- Flags and options live in `kengash <command> --help`, not in the skill.
- Give the shape of any output as a template.
- References sit one level deep and are named by their trigger: "read `references/importance.md` when assigning importance".
- Step 0 of every installed skill runs `kengash --version`. If it does not print `kengash-ai <version>`, the skill prints the install line and stops.

## Invocation

- Names are short (`plan`, `grill`, `ticket`, `loop`, `ui`, `memory`): the `kengash` plugin namespace makes them `/kengash:<name>`, and Codex copies are renamed `kengash-<name>` at install time.
- User commands (`grill`, `plan`, `ticket`, `loop`, `ui`) set `disable-model-invocation: true` for Claude Code, so only the user starts them.
- Model-invoked skills (`memory`) need sharp triggers, because the agent decides when to load them.

## Test first

Skills are built like code, test first (superpowers `writing-skills`):

1. **RED**: write a scenario and run it without the skill; record how the agent fails.
2. **GREEN**: write the smallest skill that makes the scenario pass.
3. **REFACTOR**: find new loopholes, close them, re-run.

`kengash skills eval <skill> --agent claude,codex,antigravity` replays `evals/<skill>/*.yaml` scenarios headless against a temporary store, so each skill is proven on every supported agent; `--baseline` runs them without the skills for the RED step. The scenario format is in `evals/README.md`.

## Enforcement

`kengash skills lint` (sub-project 4) runs in CI and at install time. It checks the frontmatter, the "Use when" prefix and description length, the line and word caps, and that every `kengash` command a skill mentions exists in the CLI.

## Distribution

| Route | Where skills land |
|---|---|
| `kengash skills install --agent claude [--global]` | the plugin folder `.claude/skills/kengash/` (`~/.claude/skills/kengash/`), loaded as `kengash@skills-dir` |
| `kengash skills install --agent antigravity` | `agy plugin install` of the plugin built in a temporary folder (agy copies it to `~/.gemini/config/plugins/kengash/`); `kengash-<name>` copies if that fails |
| `kengash skills install --agent codex [--global]` | `kengash-<name>` copies in `.agents/skills/` (`~/.agents/skills/`) |
| Claude Code's marketplace | `/plugin marketplace add normatov07/kengash-ai`, then `/plugin install kengash@kengash-ai` |

Role skills are never installed into agents: `kengash` injects them into worker sessions.

- Format: `src/kengash_ai/roles/<role>/SKILL.md` with `name` and `description`; workers get the body without the frontmatter.
- Lookup: a built-in role skill always comes from the package, so it cannot drift or be edited (copy the agent to change what it does); a user's skill comes from `projects/<slug>/roles/<role>/SKILL.md`, then `defaults/roles/`.
- Install folders: the claude plugin in `.claude/skills/kengash/`, codex copies (and agy's fallback) in `.agents/skills/` in a repo; with `--global`, `~/.claude/skills/kengash/`, `~/.agents/skills/` and `~/.gemini/config/skills/`. Antigravity reads its plugin manifest from `.antigravity-plugin/plugin.json`.
