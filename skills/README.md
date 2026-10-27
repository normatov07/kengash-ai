# skills

The skills you install into your agent: Claude Code, Codex or Antigravity. Each `<name>/SKILL.md` is one skill in the Agent Skills format.

| Skill | You type | It does |
|---|---|---|
| `to-plan-with-grill` | `/to-plan-with-grill <request> [project]` | asks you rounds of questions with recommended answers, then writes a plan another agent reviews |
| `to-plan` | `/to-plan <request> [project]` | writes the plan without questions; every open call becomes an assumption |
| `to-ticket` | `/to-ticket <plan id or prompt> [project]` | slices an approved plan into tickets you check first |
| `to-loop` | `/to-loop [project]` | runs the queued tickets through their workers and brings you each decision; every project unless you name one |
| `open-ui` | `/open-ui` | opens the local web UI (starting or reusing it) and gives you its link; offers to install the UI extra when it is missing |
| `kengash-memory` | (loads itself) | records lasting preferences and decisions through `kengash memory add` |

- `[project]` is a project name or its folder; an unregistered folder is offered for `kengash init`, never registered without your yes.
- Install with `kengash skills install --agent claude,codex,antigravity` (add `--global` for every project), or `npx skills add normatov07/kengash-ai`.
- The rules they follow are in `docs/conventions/skills.md`; `kengash skills lint` checks them, and `evals/` proves each one on real agents (`make evals`).
- Role skills, which only workers read, live in `src/kengash_ai/roles/`.
