# Architecture

System map of Kengash AI. The contract is the spec, `docs/superpowers/specs/2026-10-22-kengash-design.md`; this page records what exists now. Update the Status columns whenever a module or sub-project lands.

## Flow

```
You ──prompt──▶ CONDUCTOR: your claude | codex | agy session, running installed skills
                      │ shell calls, compact output
                      ▼
                 kengash CLI (deterministic) ──starts──▶ detached workers, one per job
                      │                                        │ one CLI session per ticket×role, resumed
                      ▼                                        ▼
                 store ~/.kengash                        claude -p · codex exec · agy -p
                 (Markdown + JSONL, a git repo)          (official binaries, the user's login)
                      ▲
UI: kengash ui → FastAPI + SSE on 127.0.0.1, through the same `ops` layer as the CLI
```

## Modules

| Module | Responsibility | May import | Status |
|---|---|---|---|
| `cli` | Typer command surface, output formatting | `ops`, `model` | `--version`, `init`, `doctor`, `link`, `adopt`, `settings`, `memory` (incl. `compact`), `context`, `plan` (incl. `review`), `ticket` (incl. `changes`, `attach`), `status`, `next`, `run`, `wait`, `approve`, `park`, `stop`, `pause`, `resume`, `merge`, `skills lint|install|eval`; `agent new|edit|copy|show|remove`, `workflow new|rename|remove|route|set` (SP10); `loop claim|release|status`, `skills show` (SP11); `ps`, `logs` (SP12) |
| `model` | Pydantic schemas: Plan, Ticket, Settings, Event, StepRequest, StepResult, Verdict | — | Plan, Ticket, TicketInput, Registry, Settings, Event, errors (SP2 M1–M3); runtime files, provider options (SP3 M1); step contract, provider status, trust file (SP3 M2); worker, ticket-state, cursor files (SP3 M3); job kinds, `WaitTimeout` (SP3 M4); custom steps, `role_of`/`kind_of` (SP6); `LoopLease`, `LoopBusy`, `loop_start` (SP11) |
| `store` | Paths, frontmatter, atomic writes, locks, status moves, registry, links, store commits | `model` | built (SP2 M1); runtime slots, claims, pause flags (SP3 M1); repo trust digests (SP3 M2); UI record, `yamledit` (SP5); loop leases (SP11) |
| `settings` | Seed, load, validate, resolve; comment-preserving edits | `model`, `store` | built (SP2 M2); comment-preserving writes, overrides (SP5 M2) |
| `memory` | MEMORY/DECISIONS/PROCESS writes and caps | `model`, `store`, `journal`, `settings` | built (SP2 M2): MEMORY and DECISIONS writes; compaction checks and writes, DECISIONS archive (SP3 M4) |
| `journal` | Append-only JSONL events, follow, usage aggregates | `model`, `store` | built (SP2 M2): append, read; positions (SP3 M3); day files (SP5 M2) |
| `ops` | Use cases shared by CLI, UI and workers | all units above; starts workers as processes | `projects`, `workspace`, `records`, `plans`, `tickets`, `status` (SP2 M1–M3); `queue` (SP3 M1); `terminals`, `viewers`, `watch`, `notify` (SP13); `providers` (SP3 M2); `slots`, `agents`, `prompts`, `lifecycle`, `steps`, `controls`, `merging`, `waiting`, `changes` (SP3 M3); `calls`, `jobs`, `reviews`, `compaction` (SP3 M4); `skills` (SP4 M1); `evals` (SP4 M2); `views`, `ui_server` (SP5 M1); `configure`, the screen views (SP5 M2); `agent_config` (SP6); `workflows` (SP10); `conductors`, `leases`, `loops` (SP11); `activity`, `progress`, `hygiene` (SP12); `checks` (SP15) |
| `scheduler` | Runnable set: dependencies, `touches` overlap, provider slots, fairness | `model` | built (SP3 M1) |
| `workflow` | Step graph per importance, routing, loop and budget caps, stalls | `model` | built (SP3 M1) |
| `adapters` | One driver per provider CLI behind the `Provider` protocol | `model` | built (SP3 M2): claude, codex, antigravity, shell; models per CLI and `known_models` (SP10); stream-json for claude and agy, `network` errors, a valid output winning over a late error, stamped logs (SP12) |
| `gitops` | Worktrees, commits with trailers, diffs, rebase, merge | `model` | built (SP3 M2) |
| `worker` | Runs one job through `ops`; heartbeats; handles signals | `ops`, `model` | built (SP18 adds `harvest`; SP3 M3–M4): `ticket`, `plan-review` and `compact` jobs |
| `roles` | Packaged role skill files (data only) | — | built (SP4 M1): seven role skills, always read from the package (SP10) |
| `ui` | FastAPI app, SSE, static assets | `ops`, `model` | built (SP5 M1–M2, canvas parity): token auth, Host, Origin and `X-Harness` checks, journal SSE, the seven screens matching the canvas, settings saves; New agent (SP6); controls kit, Agents and Workflow editors, folding nav (SP10); loop line and Auto mode switch (SP11); the Live tab, activity cells, pulsing cards (SP12) |

`adapters` and `gitops` never touch the store. Import-linter (`make lint`) enforces the layers `cli | worker | ui > ops > memory > journal | settings > store > model` (`journal` and `settings` independent of each other) and keeps `cli`, `worker` and `ui` from importing `store`, `settings`, `memory` or `journal` directly; `workflow`, `scheduler`, `adapters` and `gitops` import only `model`; each new module adds its contract.

## Store (built in SP2 M1)

```
~/.kengash/                      canonical store, a git repo (mode 0700)
├── registry.yaml                slug → repo path, base branch
├── memory/                      MEMORY.md, DECISIONS.md (global), archive/
├── defaults/                    SETTINGS.md, PROCESS.md, roles/ (users' skills)
├── projects/<slug>/             SETTINGS.md, PROCESS.md, memory -> ../../memory,
│                                plans/, tasks/{in_queue,in_process,done}/
├── journal/YYYY-MM-DD.jsonl     events
├── worktrees/<slug>/kg-<id8>/   ticket worktrees (git-ignored)
└── runtime/                     locks, pids, heartbeats, loop leases, logs (git-ignored)
```

Each registered repo gets one directory symlink, `<repo>/.kengash -> ~/.kengash/projects/<slug>`, listed in its `.git/info/exclude`.

## Repository layout

- `src/kengash_ai/`: the package; each module has `docs/modules/<module>/README.md`
- `scripts/`: repository checks (`check_md_caps.py`, `check_docs_sync.py`), run by `make docs`, pre-commit and CI
- `evals/`: skill eval scenarios (`make evals`, never in `make check`)
- `tests/`: the pytest suite (`make test`); `tests/live/` runs the real CLIs (`make live`, never in `make check`)
- `docs/`: index in `docs/README.md`
- `skills/`: installed skills (data; force-included in the wheel); `.claude-plugin/` and `.antigravity-plugin/`: plugin manifests

## Sub-projects

| # | Sub-project | Status |
|---|---|---|
| 1 | Foundation | done: `docs/superpowers/plans/2026-10-22-foundation.md`; CI runs after the first push |
| 2 | Store + `kengash` CLI | done: M1 store core, M2 settings, memory, journal, M3 plans and tickets; plans in `docs/superpowers/plans/` |
| 3 | Engine | done: spec `docs/superpowers/specs/2026-10-22-sp3-engine-design.md`; M1 engine rules, M2 providers and git, M3 workers and controls, M4 plan review, compaction and live smoke (green for claude and agy on 2026-10-23; codex once installed) |
| 4 | Skills | done: spec `docs/superpowers/specs/2026-10-23-sp4-skills-design.md`; M1 skill toolkit and role skills, M2 eval runner, M3 the five installed skills (evals green on claude and agy on 2026-10-23; codex once installed) |
| 5 | Web UI | done: spec `docs/superpowers/specs/2026-10-23-sp5-ui-design.md`; M1 server and monitor screens, M2 inspect and configure screens, canvas parity, M3 the `open-ui` skill (eval green on claude and agy on 2026-10-24) and the parity checklist |
| 6 | Custom agents | done: spec `docs/superpowers/specs/2026-10-26-sp6-custom-agents-design.md`; custom steps of kind read, edit or review, `kengash agent new\|remove`, the New agent dialog, CI fixed for GitHub runners and macOS, canvas follow-ups; Antigravity serves Google's subscription plans (SP7 replaced the gemini provider) |
| 7 | Production readiness | done: spec `docs/superpowers/specs/2026-10-26-sp7-production-design.md`; content-keyed parse caches (views 24 s → under 1 s on 1,500 tickets), UI security headers, ruff security rules, log retention, Windows guard, clean artifacts with `scripts/check_dist.py`, CI on 3.12–3.14 with package and audit jobs, a tag-driven PyPI release with attestations, Dependabot, accessibility (axe clean), community docs; Antigravity replaces the gemini provider |
| 8 | Kengash naming | done: spec `docs/superpowers/specs/2026-10-26-sp8-kengash-naming-design.md`; command `kengash` (`harness`/`hrn` deprecated until 0.3.0), store `~/.kengash` with a one-time link-leaving move, `.kengash` links, `KENGASH_*` variables, `kg(`/`kg/` and `Kengash-*` git names with 0.1.0 forms still read, `kengash-memory` |
| 9 | Completion audit | done: spec `docs/superpowers/specs/2026-10-27-sp9-completion-audit-design.md`; `--project/-p` takes a project name or folder, `/to-loop`, `/to-ticket`, `/to-plan` and `/to-plan-with-grill` take an optional project, tags on board cards, kengash names in make targets, scripts and the live suite |
| 10 | Agents and workflows | done: spec `docs/superpowers/specs/2026-10-30-sp10-agents-workflows-design.md`; skills as the `kengash` plugin (`/kengash:<name>`, Codex `$kengash-<name>`), built-in role skills fixed in the package, `agent edit\|copy\|show`, `workflow new\|rename\|remove\|route\|set` and `routing`, the controls kit, the Agents and Workflow screens rebuilt, Settings' planning and merging, every screen from 360 px |
| 11 | Auto flow | done: spec `docs/superpowers/specs/2026-11-06-sp11-auto-flow-design.md`; approved plans hand over to tickets and tickets to the loop through `kengash skills show`, `loop_start: ask\|auto` (Auto mode in Settings and on Overview), loop leases (`kengash loop claim\|release\|status`, exit 6) keep one live loop per project, `wait` reports `queued` tickets |
| 12 | Worker reliability and visibility | done: spec `docs/superpowers/specs/2026-11-06-sp12-worker-reliability-design.md`; a schema-valid output survives a late CLI error, `network` errors resume once then use the fallback (`fallback_on_error`), failures name the worktree, sessions survive failures; workers stream, `wait` prints progress, `kengash ps` and `kengash logs -f` (a background task the user opens), the UI Live tab; detected test and lint commands with a checks step, doctor fixes for old defaults, a 1,000,000 token cap |
| 15 | Feedback loop | done: spec `docs/superpowers/specs/2026-11-07-sp15-feedback-loop-design.md`; the project's checks run inside editing steps with fix turns on the same session (`checks.turns`), a failure digest (`adapters.digest`) in Findings and `## Check output`, prompts name the checks and the step that sent a ticket back, agy implementers may run the checks, `run_tests` reuses a pass on the same commit, a `BLOCKED:` handoff stops the ticket (`approve --note`); live agy probe and a chess-samurai replay green on 2026-11-07 |
| 16 | Shared memory and parallel tickets | done: spec `docs/superpowers/specs/2026-11-07-sp16-memory-parallel-design.md`; every new worker session gets a `## Memory` digest (PROCESS notes, decisions, preferences); plans record `## Lasting decisions` on approval and workers' proposed `decisions` land with the merge; `kengash memory add --process`, near-duplicate memory and a `# Record` hint in `kengash context`; planning neither holds nor checks paths, a planner's `files` narrow `touches`, only editors hold paths and others wait as `waiting_paths`, the longest dependency chain starts first, edits start from the newest base, merges take turns and recheck a moved base, and `merge.mode` defaults to `auto` |
| 17 | Throughput | built, awaiting a live run: spec `docs/superpowers/specs/2026-11-08-sp17-throughput-design.md`; a stuck CLI call is stopped and resumed with a correction (`adapters.watchdog`, `steering`), a finishing worker starts what is runnable (`ops.relay`), path claims allow generated files and small overlaps (`scheduler.clash`), large tickets split (`parts`), new editing sessions get the plan's files read at that moment (`ops.context`), review findings are checked (`review.block_on`), and each agent has a model per importance |
| 18 | Capture and width | built: spec `docs/superpowers/specs/2026-11-09-sp18-capture-width-design.md`; the memory harvest job and its triggers, `ticket add --check`, `needs` on every dependency, claims that follow the edits, stuck tickets named |
| 19 | Landing | built: spec `docs/superpowers/specs/2026-11-09-sp19-landing-design.md`; merge conflicts settled inside the ticket, `project.generate_cmd`, `project.commands`, rebase before review |
| 20 | Balance | built: spec `docs/superpowers/specs/2026-11-09-sp20-balance-design.md`; the relay covers live loops, contracts between tickets, escalation on failure, `kengash stats` |

## Agent context files

| Agent | Reads | Verified |
|---|---|---|
| Claude Code | `CLAUDE.md`, which imports `AGENTS.md` with `@AGENTS.md` | documented import syntax |
| Codex | `AGENTS.md` natively | documentation only; Codex CLI is not installed on the dev machine |
| Gemini CLI | `GEMINI.md`, which imports `AGENTS.md` with `@AGENTS.md` | documentation only; Gemini CLI is not installed |
| Antigravity `agy` | `AGENTS.md` (legacy `GEMINI.md` also supported) | 2026-10-22, agy 1.4.5: a headless run quoted hard rule 3 from `AGENTS.md` with `GEMINI.md` present |
