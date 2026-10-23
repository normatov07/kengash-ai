# Architecture

System map of super-harness. The contract is the spec, `docs/superpowers/specs/2026-10-22-super-harness-design.md`; this page records what exists now. Update the Status columns whenever a module or sub-project lands.

## Flow

```
You ──prompt──▶ CONDUCTOR: your claude | codex | agy session, running installed skills
                      │ shell calls, compact output
                      ▼
                 harness CLI (deterministic) ──starts──▶ detached workers, one per job
                      │                                        │ one CLI session per ticket×role, resumed
                      ▼                                        ▼
                 store ~/.harness                        claude -p · codex exec · agy -p
                 (Markdown + JSONL, a git repo)          (official binaries, the user's login)
                      ▲
UI: harness ui → FastAPI + SSE on 127.0.0.1, through the same `ops` layer as the CLI
```

## Modules

| Module | Responsibility | May import | Status |
|---|---|---|---|
| `cli` | Typer command surface, output formatting | `ops`, `model` | `--version`, `init`, `doctor`, `link`, `adopt`, `settings`, `memory`, `context`, `plan`, `ticket`, `status`, `next` |
| `model` | Pydantic schemas: Plan, Ticket, Settings, Event, StepRequest, StepResult, Verdict | — | Plan, Ticket, TicketInput, Registry, Settings, Event, errors (SP2 M1–M3); runtime files, provider options (SP3 M1) |
| `store` | Paths, frontmatter, atomic writes, locks, status moves, registry, links, store commits | `model` | built (SP2 M1); runtime slots, claims, pause flags (SP3 M1) |
| `settings` | Seed, load, validate, resolve; comment-preserving edits | `model`, `store` | built (SP2 M2); comment-preserving edits in SP5 |
| `memory` | MEMORY/DECISIONS/PROCESS writes and caps | `model`, `store`, `journal`, `settings` | built (SP2 M2): MEMORY and DECISIONS writes; compaction in SP3 |
| `journal` | Append-only JSONL events, follow, usage aggregates | `model`, `store` | built (SP2 M2): append, read; follow and usage later |
| `ops` | Use cases shared by CLI, UI and workers | all units above; starts workers as processes | `projects`, `workspace`, `records`, `plans`, `tickets`, `status` (SP2 M1–M3); `queue` (SP3 M1); grows in SP3, SP5 |
| `scheduler` | Runnable set: dependencies, `touches` overlap, provider slots, fairness | `model` | built (SP3 M1) |
| `workflow` | Step graph per importance, routing, loop and budget caps, stalls | `model` | built (SP3 M1) |
| `adapters` | One driver per provider CLI behind the `Provider` protocol | `model` | core and shell (SP3 M2) |
| `gitops` | Worktrees, commits with trailers, diffs, rebase, merge | `model` | worktrees, commits, diffs (SP3 M2) |
| `worker` | Runs one job through `ops`; heartbeats; handles signals | `ops`, `model` | planned, SP3 |
| `roles` | Packaged role skill files (data only) | — | planned, SP4 |
| `ui` | FastAPI app, SSE, static assets | `ops`, `model` | planned, SP5 |

`adapters` and `gitops` never touch the store. Import-linter (`make lint`) enforces the layers `cli > ops > memory > journal | settings > store > model` (`journal` and `settings` independent of each other) and keeps `cli` from importing `store`, `settings`, `memory` or `journal` directly; `workflow` and `scheduler` import only `model`; each new module adds its contract.

## Store (built in SP2 M1)

```
~/.harness/                      canonical store, a git repo (mode 0700)
├── registry.yaml                slug → repo path, base branch
├── memory/                      MEMORY.md, DECISIONS.md (global), archive/
├── defaults/                    SETTINGS.md, PROCESS.md, roles/ (seeds)
├── projects/<slug>/             SETTINGS.md, PROCESS.md, memory -> ../../memory,
│                                plans/, tasks/{in_queue,in_process,done}/
├── journal/YYYY-MM-DD.jsonl     events
├── worktrees/<slug>/hrn-<id8>/  ticket worktrees (git-ignored)
└── runtime/                     locks, pids, heartbeats, logs (git-ignored)
```

Each registered repo gets one directory symlink, `<repo>/.harness -> ~/.harness/projects/<slug>`, listed in its `.git/info/exclude`.

## Repository layout

- `src/super_harness/`: the package; each module has `docs/modules/<module>/README.md`
- `scripts/`: repository checks (`check_md_caps.py`, `check_docs_sync.py`), run by `make docs`, pre-commit and CI
- `tests/`: the pytest suite (`make test`)
- `docs/`: index in `docs/README.md`
- `skills/` and `.claude-plugin/`: arrive in SP4

## Sub-projects

| # | Sub-project | Status |
|---|---|---|
| 1 | Foundation | done: `docs/superpowers/plans/2026-10-22-foundation.md`; CI runs after the first push |
| 2 | Store + `harness` CLI | done: M1 store core, M2 settings, memory, journal, M3 plans and tickets; plans in `docs/superpowers/plans/` |
| 3 | Engine | in progress: spec `docs/superpowers/specs/2026-10-22-sp3-engine-design.md`; M1 engine rules built; M2 providers and git next |
| 4 | Skills | planned |
| 5 | Web UI | planned |

## Agent context files

| Agent | Reads | Verified |
|---|---|---|
| Claude Code | `CLAUDE.md`, which imports `AGENTS.md` with `@AGENTS.md` | documented import syntax |
| Codex | `AGENTS.md` natively | documentation only; Codex CLI is not installed on the dev machine |
| Gemini CLI | `GEMINI.md`, which imports `AGENTS.md` with `@AGENTS.md` | documentation only; Gemini CLI is not installed |
| Antigravity `agy` | `AGENTS.md` (legacy `GEMINI.md` also supported) | 2026-10-22, agy 1.4.5: a headless run quoted hard rule 3 from `AGENTS.md` with `GEMINI.md` present |
