# Sub-project 4: Skills — Spec

- Date: 2026-10-23
- Status: approved by default (user prefers momentum; assumptions listed in §2 for veto)
- Implements: system spec `2026-10-22-super-harness-design.md` §8 (installed skills, role skills, writing standard, distribution), §12 (`--cli-name hrn` and the doctor clash report), roadmap row 4; conventions `docs/conventions/skills.md`.
- This spec only adds what the system spec leaves open. System spec changes it needs (§2) are made in the same commit.
- CLI facts checked on 2026-10-23 without model calls: claude 2.1.309 (`claude plugin validate`, `claude plugin eval`), agy 1.4.5 (`agy plugin validate`; workspace skills in `.agents/skills/`; `--disable-slash-commands` disables "slash command and skill expansion in print mode", so print mode expands skills). Codex is not installed on the dev machine: its paths come from its documentation only.

## 1. Milestones

Each milestone is planned just before it is built, ends green on `make check`, and is reviewed against this spec.

| # | Milestone | Delivers | Exit |
|---|---|---|---|
| M1 | Skill toolkit and role skills | `ops.skills` (frontmatter, lint, install), `harness skills lint\|install`, seven role skills, role lookup and seeding, wheel packaging, plugin manifests, doctor clash report | `harness skills lint` passes on the repo and runs in `make check`; install round-trips into temp agent folders; role skills reach worker prompts |
| M2 | Eval runner | eval scenario schema, `ops.evals` (temp store, scratch repo, setup, install, multi-turn headless conductor, assertions), `harness skills eval`, a live probe of the agy conductor mode | runner tests pass against fake CLIs; one live probe scenario passes on claude and agy |
| M3 | Installed skills | `to-plan-with-grill`, `to-plan`, `to-ticket`, `to-loop`, `harness-memory`, each test first: RED without it, GREEN with it | every scenario passes on claude and agy (`make evals`); codex once installed |

## 2. Decisions (assumed defaults — veto any)

1. **`open-ui` moves to SP5.** Its only command, `harness ui open`, arrives with the UI, and lint refuses skills that name missing commands. SP4 ships the other five installed skills. (System spec §13 row 4 changed.)
2. **One source per skill.** Installed skills live at the repo root, `skills/<name>/SKILL.md`, where `npx skills add` and plugin marketplaces find them; the wheel force-includes them as `super_harness/skills/`. `ops.skills.packaged()` finds them in the package, else in the source checkout. Role skills live in `src/super_harness/roles/<role>/SKILL.md`.
3. **Role skills use the skill format** (`roles/<role>/SKILL.md`, frontmatter `name` and `description`). Workers inject the body without its frontmatter. Lookup: project `roles/` → `defaults/roles/` → package. `harness init` seeds missing ones into `defaults/roles/` and never overwrites them. The flat `roles/<name>.md` files that SP3 looked up are no longer read.
4. **Install targets.** `harness skills install --agent claude,codex,antigravity [--global] [--path DIR] [--cli-name hrn] [--yes]`: claude → `<root>/.claude/skills/<name>/`, codex and antigravity → `<root>/.agents/skills/<name>/` (one copy serves both). The root is the repo containing `--path` (default: the current folder). `--global` writes claude → `~/.claude/skills/`, codex → `~/.agents/skills/` (documented), antigravity → `~/.gemini/config/skills/` (§5).
5. **Install is safe to repeat.** Each skill folder is written atomically. A skill that is missing is installed, one that is identical is left alone, and one that differs prints a unified diff and is replaced only with `--yes` (exit 5 otherwise). Installs never delete files outside the skills they write.
6. **`--cli-name hrn`** rewrites every `harness ` command prefix in installed text to `hrn `. `harness doctor` warns when the first `harness` on `PATH` is not super-harness's own (it compares `harness --version`), naming `--cli-name hrn`.
7. **Lint** runs on installed skills (all §8.3 rules: frontmatter, `name` equals the folder, "Use when" and at most 500 characters, at most `skill.max_lines` lines and `skill.max_words` words, step 0 runs `harness --version`, `references/` one level deep and every named reference present, every `harness <command> [<subcommand>]` mentioned exists) and on role skills (frontmatter, `name` equals the folder, the caps). `cli` hands the command tree to `ops`, since `ops` never imports `cli`. `make check` runs `harness skills lint`.
8. **Install line.** Step 0 of every installed skill: run `harness --version`; if it does not print `super-harness <version>`, print `Install super-harness first: uv tool install git+https://github.com/normatov07/super-harness` and stop.
9. **Frontmatter.** User skills set `disable-model-invocation: true` (Claude Code); `harness-memory` does not. Both carry `metadata: {source: super-harness}`; agents ignore keys they do not know, and `agy plugin validate` must accept them.
10. **Plugin manifests.** `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` make the repo root one plugin with `skills/`; agy loads the same layout. `claude plugin validate .` and `agy plugin validate .` run in a live-marked test. A Codex manifest waits until codex is installed and its format can be checked.
11. **Eval scenarios** live at the repo root, `evals/<skill>/<scenario>.yaml`, never installed. A scenario names the skill, optional repo files, settings and setup commands (`harness` argv plus stdin; `save: <name>` keeps the first 8-hex-digit word the command printed, and later strings use it as `{name}`), conductor turns (the first usually `/<skill> …`; later turns answer the agent), and expectations: journal event types that must appear (and ones that must not), and counts or field values of plans and tickets.
12. **Eval runs.** For each scenario and agent: a temporary `HARNESS_HOME` and scratch repo, `harness init`, the setup commands, `harness skills install --agent <agent>` into the scratch repo, then each turn headless in the scratch repo, resuming the conductor's session (claude `-p --resume`, agy `-p --conversation`, codex `exec resume`), then the expectations. The conductor runs on the agent's cheapest model (claude `haiku`, agy `gemini-3.8-flash-low`, codex default; `--model` overrides) without the user's personal setup, like workers (M2's probe confirms that claude still loads the scratch repo's `.claude/skills/` with `--setting-sources project,local`). Results print one line per scenario and agent; `--json` gives the transcript paths. Exit 0 all pass · 1 a failure · 4 an agent missing or signed out.
13. **Conductor permissions in evals.** claude: `--permission-mode dontAsk --allowedTools Read Grep Glob "Bash(harness:*)"`. agy has no per-command allowlist; M2's probe picks the least permissive mode in which headless agy runs `harness` (in order: `--mode accept-edits`, `--sandbox`, `--dangerously-skip-permissions --sandbox`) and records it in §5. Evals are opt-in, run by the developer, inside temporary folders.
14. **Skills give long commands a timeout.** `harness wait` and `harness plan review` block up to 540 s; skills tell the agent to give its shell tool a 10-minute timeout and to rerun on exit 3.
15. **Stdin through heredocs.** Skills pass plan text, ticket lists and prompts with `harness … <<'EOF'` so the command line starts with `harness` and matches the conductor's allowlist.
16. **Writing test first.** Each installed skill's first scenario is run before the skill exists (RED, the failure recorded in the scenario's `notes:`), then the smallest skill that passes is written (GREEN), then loopholes found in transcripts are closed (REFACTOR). Role skills are proven by the live smoke instead of evals.
17. **`make evals`** runs every scenario on every installed agent; like `make live`, it spends subscription quota and never runs in `make check`.

## 3. Units

| Unit | Holds | May import |
|---|---|---|
| `skills/` (repo root) | installed skills, data only | — |
| `roles` (`src/super_harness/roles/`) | role skills, data only | — |
| `evals/` (repo root) | eval scenarios, data only | — |
| `model` (adds `skills`) | `SkillMeta`, `LintProblem`, `EvalScenario` and its parts | — |
| `ops` (adds `skills`, `evals`) | lint, install, packaged lookup, role skill text and seeding; the eval runner | `adapters` (process runner), store, settings, journal |
| `cli` (adds `skills lint\|install\|eval`) | the command tree for lint; output formatting | `ops`, `model` |

## 4. Output

| Command | Output (default) | Exit codes |
|---|---|---|
| `harness skills lint [PATH…]` | one `<path>: <problem>` line per problem; nothing when clean | 0 · 1 problems |
| `harness skills install --agent A,… [--global] [--path DIR] [--cli-name N] [--yes]` | `<agent> <name>: installed\|updated\|unchanged → <folder>` per skill (capped), diffs for skills that differ without `--yes` | 0 · 1 unknown agent · 5 a skill differs and `--yes` is missing |
| `harness skills eval <skill>\|--all [--agent A,…] [--model M]` | `<skill>/<scenario> <agent>: pass\|fail: <first failed expectation>` per run | 0 · 1 · 4 |

## 5. Live facts (filled in during the build)

- agy skills folders: `<workspace>/.agents/skills/<name>/SKILL.md` and, globally, `~/.gemini/config/skills/<name>/SKILL.md` (path strings in the agy 1.4.5 binary, 2026-10-23); the M2 probe confirms that headless agy loads the workspace one.
- agy conductor mode for evals: (M2 probe)

## 6. Acceptance (SP4 exit)

- [ ] `harness skills lint` is clean on `skills/` and `src/super_harness/roles/`, and runs in `make check`.
- [ ] `harness skills install` writes each agent's folders, is idempotent, shows diffs before replacing, and `--cli-name hrn` rewrites commands; `harness doctor` reports a foreign `harness` on `PATH`.
- [ ] Workers inject packaged role skills unless the defaults or the project override them.
- [ ] `claude plugin validate .` and `agy plugin validate .` pass.
- [ ] Every eval scenario fails without its skill and passes with it, on claude and agy; codex once installed.
- [ ] Module docs for the new units; `make check` green.
