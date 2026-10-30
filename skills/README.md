# skills

The skills you install into your agent: Claude Code, Codex or Antigravity. Each `<name>/SKILL.md` is one skill in the Agent Skills format; together they are the `kengash` plugin.

| Skill | You type | It does |
|---|---|---|
| `grill` | `/kengash:grill <request> [project]` | asks you rounds of questions with recommended answers, then writes a plan another agent reviews |
| `plan` | `/kengash:plan <request> [project]` | writes the plan without questions; every open call becomes an assumption |
| `ticket` | `/kengash:ticket <plan id or prompt> [project]` | slices an approved plan into tickets you check first |
| `loop` | `/kengash:loop [project]` | runs the queued tickets through their workers and brings you each decision; every project unless you name one |
| `ui` | `/kengash:ui` | opens the local web UI (starting or reusing it) and gives you its link; offers to install the UI extra when it is missing |
| `memory` | (loads itself) | records lasting preferences and decisions through `kengash memory add` |

- `[project]` is a project name or its folder; an unregistered folder is offered for `kengash init`, never registered without your yes.
- Install with `kengash skills install --agent claude,codex,antigravity` (add `--global` for every project). Claude Code gets a plugin folder in `.claude/skills/kengash/`, Antigravity installs the plugin with `agy plugin install`; both show `/kengash:<name>`. Codex has no plugin namespace, so it gets `kengash-<name>` copies in `.agents/skills/`, typed `$kengash-<name>`.
- The rules they follow are in `docs/conventions/skills.md`; `kengash skills lint` checks them, and `evals/` proves each one on real agents (`make evals`).
- Role skills, which only workers read, live in `src/kengash_ai/roles/`.
