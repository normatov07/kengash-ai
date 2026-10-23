# skills

The skills you install into your agent: Claude Code, Codex or Antigravity. Each `<name>/SKILL.md` is one skill in the Agent Skills format.

- Install with `harness skills install --agent claude,codex,antigravity` (add `--global` for every project), or `npx skills add normatov07/super-harness`.
- The rules they follow are in `docs/conventions/skills.md`; `harness skills lint` checks them.
- Role skills, which only workers read, live in `src/super_harness/roles/`.
