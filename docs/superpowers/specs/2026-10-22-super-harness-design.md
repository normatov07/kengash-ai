# super-harness: System Design and Foundation Spec

- Date: 2026-10-22
- Status: draft, awaiting user review
- Scope: system-wide contracts for all five sub-projects, plus the full design of sub-project 1 (Foundation). Sub-projects 2–5 each get their own spec, which must conform to the contracts here.
- Requirements: `full prompt of app.md`. Where it conflicts with this spec, this spec wins (see §2).
- UI source of truth: Claude Design canvas https://claude.ai/artifact/JiMGMkbaw8qhafeaNbqU7d

## 1. Goal and success criteria

One developer runs many projects at once with only subscription coding-agent CLIs (Claude Code, Codex, Antigravity `agy`; Gemini CLI optional), never API keys. A prompt becomes an approved plan, the plan becomes tickets, tickets run through importance-based agent loops, and a local UI monitors and controls everything. Open source, installable into any agent that supports Agent Skills.

| # | Success criterion | Verified by |
|---|---|---|
| S1 | From Claude Code, Codex or agy, `/to-plan` → `/to-ticket` → `/to-loop` takes a ticket to done using only CLI subscriptions | live smoke test per provider (SP3, SP4) |
| S2 | Tickets of two or more projects run at once; within a project, tickets with disjoint `touches` run in parallel and overlapping ones run one by one | scheduler unit tests, integration test |
| S3 | No ticket runs past `loop_max` or its token budget without an explicit user grant | workflow unit tests |
| S4 | Every step records provider, model, session id, tokens, duration and verdict; every code change carries the ticket uuid in git trailers, findable after merge | integration test |
| S5 | A ticket×role session is created once and resumed on every later loop | adapter contract tests |
| S6 | Conductor overhead stays small: status and action commands print at most 5 lines by default; installed skills stay within 80 lines and 400 words | `harness skills lint`, output tests |
| S7 | The UI implements all seven canvas screens with live updates | SP5 parity checklist |
| S8 | Every state change is atomic; a dead worker or a broken link is detected and repairable | store tests, `harness doctor` tests |

Non-goals for v1: API-key billing; remote or cloud execution; a multi-user server; the SQLite index and vector recall (the canvas marks both "planned"); native Windows (WSL works); the Antigravity IDE (only the `agy` CLI).

## 2. Decisions

| # | Decision | Rejected alternatives, and why |
|---|---|---|
| D1 | Five layered sub-projects built in order 1→5, each spec → plan → build → critical review | thin vertical slice first (more rework); UI first (CLI risks surface late) |
| D2 | The user's interactive agent is the conductor; a deterministic `harness` CLI does every mechanical step; no always-on daemon | always-on engine daemon (user wants their agent in control and nothing extra to run); LangGraph or ACP framework (second source of truth, heavy dependencies) |
| D3 | The `~/.harness` store is canonical; one directory symlink per project | per-file hard links (cannot link directories; status moves and atomic saves split them; same disk only); project-local canonical store (moving a project breaks the index; personal memory leaks into team repos) |
| D4 | One plan file per request and one file per ticket, linked by id; the plan holds the verbatim prompt | one file holding all tickets (status folders lose meaning; lock contention); prompt copied into every ticket (token waste; copies drift) |
| D5 | Ship as Agent Skills (`skills/<name>/SKILL.md`) plus the `harness` CLI; `harness` injects role skills into worker sessions | installing role skills into every agent (fills every session's skill list; workers would depend on per-agent install state) |
| D6 | Planning: grill rounds of up to 3 questions, each with a recommended answer; plan review by a different provider, at most 2 rounds; user approval before ticketing | strict one question per round (more round trips; still available as `grill.round_size: 1`) |
| D7 | Worker sessions are reused by resuming the CLI session id at every step | long-lived `stream-json` processes (later optimisation behind the same adapter interface); tmux-driven interactive TUIs (brittle output scraping) |
| D8 | One detached worker process per job; the conductor waits with `harness wait` | conductor driving every step (context growth); one blocking call per ticket (agent tool timeouts of about 10 minutes) |
| D9 | One git worktree and branch per ticket; harness commits after each implement step with `Harness-*` trailers | agents committing (trailers unreliable); one shared working tree (collisions) |
| D10 | Providers claude, codex and antigravity are first-class; gemini is optional | gemini first-class (consumer login shut down on 2026-06-18) |

## 3. Architecture

```
You ──prompt──▶ CONDUCTOR: your interactive agent (claude | codex | agy) running installed skills
                 /to-plan-with-grill · /to-plan · /to-ticket · /to-loop · /open-ui
                      │ shell calls; compact text out
                      ▼
                 harness CLI (Python, deterministic)
                      │ starts detached workers
                      ▼
                 WORKER: python -m super_harness.worker <job>   (ticket steps | plan review | compaction)
                      │ one CLI session per ticket×role, resumed every loop
                      ▼
                 claude -p · codex exec · agy -p        (official binaries, the user's own login)

UI: harness ui → FastAPI + SSE on 127.0.0.1 → same use-case layer as the CLI
```

### 3.1 Units

| Unit (`super_harness.*`) | Responsibility | May import |
|---|---|---|
| `model` | Pydantic schemas: Plan, Ticket, Settings, Event, StepRequest, StepResult, Verdict | — |
| `store` | Paths, frontmatter, atomic writes, locks, status moves, registry, links, store git commits, runtime files | model |
| `settings` | Seed, load, validate and resolve settings; comment-preserving edits | model, store |
| `memory` | MEMORY/DECISIONS/PROCESS writes and caps | model, store |
| `journal` | Append-only JSONL events, follow, usage aggregates | model, store |
| `scheduler` | Runnable set: dependencies, `touches` overlap, provider slots, fairness | model, store, settings |
| `workflow` | Step graph per importance, routing, loop and budget caps, stall detection | model, settings |
| `adapters` | One driver per provider CLI behind the `Provider` protocol | model |
| `gitops` | Worktrees, commits with trailers, diffs, rebase, merge | model |
| `ops` | Use cases shared by CLI and UI: plan and ticket actions, run, approve, park, stop, pause, move, merge, settings edits, memory compaction | all units above |
| `worker` | Runs one job; heartbeats; emits events | all units above except `ops` |
| `cli` | Typer command surface and output formatting | `ops`, `model` |
| `ui` | FastAPI app, SSE, static assets | `ops`, `model` |
| `roles` | Packaged role skill files (data only) | — |

Import-linter contracts enforce this table in CI. `adapters` and `gitops` never touch the store.

## 4. Store

### 4.1 Layout

```
$HARNESS_HOME (default ~/.harness, mode 0700, a git repo)
├── registry.yaml                    slug → repo path, base branch, added date
├── memory/
│   ├── MEMORY.md                    global brain (§4.5)
│   ├── DECISIONS.md                 global decision log (§4.5)
│   └── archive/                     compacted-out entries; never loaded automatically
├── defaults/
│   ├── SETTINGS.md                  seed for new projects; the UI's "Defaults" scope
│   ├── PROCESS.md                   seed
│   └── roles/<role>/SKILL.md        user-editable role skills, seeded from the package
├── projects/<slug>/
│   ├── SETTINGS.md                  copied from defaults once, never overwritten
│   ├── PROCESS.md
│   ├── roles/<role>/SKILL.md        optional per-project role override
│   ├── memory -> ../../memory       directory symlink
│   ├── plans/<id8>.md
│   └── tasks/{in_queue,in_process,done}/<id8>.md
├── journal/YYYY-MM-DD.jsonl         events (§6.1)
├── worktrees/<slug>/hrn-<id8>/      ticket worktrees                          (git-ignored)
└── runtime/                         locks, pids, heartbeats, conductor pings, logs  (git-ignored)

<repo>/.harness -> $HARNESS_HOME/projects/<slug>     listed in <repo>/.git/info/exclude
```

Settings values and role skills resolve project → defaults → package built-ins.

### 4.2 Links

| Command | Behaviour |
|---|---|
| `harness init [path]` | Idempotent. Registers the repo (slug = folder name, deduplicated as `-2`, `-3`), seeds missing SETTINGS.md and PROCESS.md, creates the `.harness` symlink and adds it to `.git/info/exclude`. Registering is the user's explicit trust of that repo. |
| `harness doctor [--fix] [--quiet] [--scan DIR]` | Checks every registry entry: repo exists, link points at the right store directory, no dead workers, frontmatter valid. `--fix` repairs links; `--quiet` prints problems only; `--scan` finds real `.harness/` folders the store does not know. |
| `harness link <slug> <new-path>` | Re-points a moved project. |
| `harness adopt <path>` | Imports a real `.harness/` folder: plans and tickets merge by uuid (on conflict the newer `updated` wins and the other copy goes to `archive/`), then the folder is replaced by the symlink. |

### 4.3 Write discipline

- Only harness writes store files. Agents change state through harness commands, or by returning JSON that harness records.
- Every write goes to a temp file in the same real directory, is fsynced, then `os.replace`d. Status moves are `os.rename` within one filesystem. Both are atomic, and both work through the project symlink because it links the directory, not the file.
- A per-project lock (`runtime/locks/<slug>.lock`, `filelock`) guards each read-modify-write. A global lock guards the registry and the slot table. A per-repo lock serialises `git worktree` and merge operations.
- After each state-changing command, harness commits the store (`harness: <command> <ids>`), so MEMORY.md, DECISIONS.md, plans and tickets keep full history.

### 4.4 Plan and ticket files

Ids are `uuid4`. The first 8 hex characters are the short id and the file name; uuid4 (not uuid7) keeps short ids from colliding within one batch. A collision within a project re-rolls the id.

Plan, `plans/<id8>.md`:

```markdown
---
id: a1b2c3d4
uuid: a1b2c3d4-…
project: payments-api
title: Rotatable webhook signing keys
mode: grill            # grill (/to-plan-with-grill) | direct (/to-plan) | quick (/to-ticket "<prompt>")
status: approved       # grilling | draft | in_review | approved | ticketed | rejected
review: {round: 2, max: 2, verdict: pass, reviewer: codex}   # reviewer verdict; approval is the user's act
milestone: 1           # milestone currently ticketed
tickets: [7b55e0c1, a91b3d07]
created: 2026-10-22T09:30:00Z
updated: 2026-10-22T09:40:00Z
---
## Prompt         the user's prompt, verbatim
## Goal           1–3 lines: outcome and why
## Decisions      one line each: question → answer
## Assumptions    one line each: unasked decision → default chosen, and why
## Scope
## Out of scope
## Design         modules, interfaces, data; no code
## Acceptance     checkable list; becomes ticket acceptance criteria
## Test seams
## Risks
## Milestones
## Review log     one line per finding per round, with its resolution
```

Ticket, `tasks/<folder>/<id8>.md`:

```markdown
---
id: 7b55e0c1
uuid: 7b55e0c1-3d42-4ab9-9f07-c81e2a6d5f10
project: payments-api
plan: a1b2c3d4
title: Rotate payment webhook signing keys
importance: critical            # simple | standard | critical
workflow: critical              # key into SETTINGS workflows
status: in_process/under_security_review
gate: afk                       # afk | hitl
loop: 6
loop_max: 6
tokens: 148600
depends_on: [a91b3d07]
touches: [services/webhooks]    # repo path prefixes; empty = whole repo, so always runs alone
tags: [payments, security]
branch: hrn/7b55e0c1
sessions:
  implementer: {provider: codex, model: default, id: 019a…}
  code-reviewer: {provider: claude, model: opus, id: 3f2c…}
created: 2026-10-22T09:41:00Z
updated: 2026-10-22T12:05:00Z
---
## Scope          what this slice delivers, end to end
## Acceptance     - [ ] checkable criteria
## Handoff        latest step's notes for the next agent; replaced each step; at most 15 lines
## Findings       open review findings: severity · file:line · issue · fix
## Log            one line per step: time · step · role · provider/model · verdict · tokens
```

Statuses, written `<folder>/<sub_status>`:

| Folder | Sub-statuses |
|---|---|
| `in_queue` | `ready`, `blocked` (a dependency is not done), `parked` |
| `in_process` | one per workflow step (from `status.names`, e.g. `under_implementation`), `waiting_slot`, `waiting_quota`, `needs_approval`, `stalled`, `failed`, `awaiting_merge` |
| `done` | `merged`, `branch_ready`, `closed` (force-moved by the user) |

### 4.5 Memory and instruction files

| File | Scope | Read by | Written by | Cap |
|---|---|---|---|---|
| MEMORY.md | global | conductor at the start of every command (via `harness context`); workers get a digest | `harness memory add` | 200 lines |
| DECISIONS.md | global; entries tagged `[project]` | planner, plan reviewer, conductor | `harness memory add --decision` | 300 lines, then the oldest move to `archive/` |
| PROCESS.md | project | workers of that project | user, conductor | 100 lines |
| SETTINGS.md | project | harness only; agents never parse it | user, UI | schema-validated |
| Ticket `## Handoff` | ticket | the next worker | harness, from worker JSON | 15 lines |

One fact per line, about 20 words at most:

```
MEMORY.md     sections: ## Working style · ## Goals · ## Preferences · ## Turned down
              - ships small, reviews hard; wants the diff, not prose
DECISIONS.md  - 2026-10-22 [payments-api] keyring over single secret, 48h overlap. why: zero-downtime rotation. rejected: one env var
```

When a file passes its cap, `ops` runs a compaction job: a one-shot worker on the cheapest configured model merges duplicates and drops stale lines. Harness accepts the result only if it is under the cap and keeps every line marked `(pin)`. The previous version stays in the store's git history.

### 4.6 SETTINGS.md

The whole file is YAML; `#` lines are YAML comments that read as Markdown headings. Harness validates it against the `Settings` schema and rejects unknown keys with a "did you mean" hint. UI edits use round-trip YAML (`ruamel.yaml`) so comments survive. The package default:

```yaml
# SETTINGS.md: harness settings for this project. YAML. Harness never overwrites this file.
version: 1

# project
project.test_cmd: ""          # e.g. "uv run pytest -q"; used by run_tests steps and reviewers
project.lint_cmd: ""

# loops
loop_max.simple: 3
loop_max.standard: 4
loop_max.critical: 6
loop_grant: 2                 # loops added per approval
loop_ask_at_cap: true         # false: park the ticket instead of asking
loop_count_rejected_review: true   # false: plan-review rejections count only toward plan.review_max
stall_repeat: 2               # the same finding fails this many loops in a row → stalled

# planning
grill.round_size: 3
plan.review_max: 2            # 0 = no plan review
plan.reviewer: different-provider   # or provider[/model]

# sessions and limits
sessions.reuse: true          # resume each ticket×role session across loops
sessions.max: 8
sessions.per_provider: {claude: 3, codex: 3, antigravity: 2, gemini: 0}
tokens.per_ticket_max: 250000
step_timeout_min: 30          # a step running longer is killed and retried once
fallback_on_rate_limit: true

# token discipline
skill.max_lines: 80
skill.max_words: 400
memory.compact_at_lines: 200
review.diff_only: true

# agents: role → CLI; an omitted model means the CLI's default model
agents:
  planner:           {on: true,  cli: claude/opus,   skill: plan}
  plan-reviewer:     {on: true,  cli: codex,         skill: review-plan}
  implementer:       {on: true,  cli: codex,         skill: implement, fallback: [claude/sonnet]}
  code-reviewer:     {on: true,  cli: claude/opus,   skill: review-code}
  security-reviewer: {on: true,  cli: claude/sonnet, skill: review-security, blocking: true}
  test-runner:       {on: false, cli: shell,         skill: run-tests}
  doc-writer:        {on: false, cli: antigravity,   skill: sync-docs}

# workflows: steps run in order; on_fail routes a failing verdict back and adds a loop
workflows:
  simple:   {steps: [plan, implement, review_code], on_fail: {review_code: implement}}
  standard: {steps: [plan, review_plan, implement, review_code],
             on_fail: {review_plan: plan, review_code: implement}}
  critical: {steps: [plan, review_plan, implement, review_code, security],
             on_fail: {review_plan: plan, review_code: implement, security: implement}}

# sub-status shown while a step runs
status.names: {plan: under_planning, review_plan: under_plan_review, implement: under_implementation,
               review_code: under_review, security: under_security_review, run_tests: under_test,
               docs: under_docs, approve: needs_approval}

# merge: ask | auto | branch
merge.mode: ask
```

## 5. Loop semantics

Steps map to roles: `plan` → planner, `review_plan` → plan-reviewer, `implement` → implementer, `review_code` → code-reviewer, `security` → security-reviewer, `run_tests` → test-runner (shell, no model), `docs` → doc-writer, `approve` → the user. A step whose role is switched off is skipped; if that role is `blocking`, the ticket fails with a message instead.

- `loop` starts at 1. A failing verdict follows the step's `on_fail` edge and adds 1 to `loop`.
- If a failing verdict arrives when `loop` already equals `loop_max`, the ticket goes to `needs_approval` (or `parked` when `loop_ask_at_cap: false`) instead of recirculating. `harness approve <id> [--loops N]` raises `loop_max` by N (default `loop_grant`), and the recirculation proceeds.
- Before every step, `tokens ≥ tokens.per_ticket_max` also sends the ticket to `needs_approval`.
- Review steps return schema-validated JSON: `{verdict: pass|fail, findings: [{severity, file, line, issue, fix}], summary}`. Each finding gets a fingerprint (normalised file plus issue text). The same fingerprint failing `stall_repeat` loops in a row → `stalled`. Planner and plan reviewer disagreeing beyond `plan.review_max` rounds → `stalled`; the same limit applies to plan-level reviews (`harness plan review`) and to tickets' `review_plan` steps.
- `gate: hitl` tickets add an `approve` step after `plan` and always require approval before merge, whatever `merge.mode` says.
- After the last step: `merge.mode: ask` → `awaiting_merge`; `auto` → merge at once if the repo's main working tree is clean and on the base branch, otherwise `awaiting_merge`; `branch` → `done/branch_ready`.
- `harness merge <id>` rebases the ticket branch onto the base branch inside its worktree (a conflict sends the ticket back to `implement` with loop + 1), runs `git merge --ff-only` in the main working tree (refused unless it is clean and on the base branch), removes the worktree, deletes the branch, and moves the ticket to `done/merged`. Harness never pushes.

## 6. Conductor contract

Status and action commands print at most 5 lines; `context` and `show` print the content asked for; `--json` gives full machine output everywhere. Exit codes: 0 ok · 1 error · 2 usage · 3 wait timeout · 4 setup needed (missing install, sign-in or init) · 5 a user decision is needed.

| Command | Purpose |
|---|---|
| `harness context [project]` | Digest for the conductor: MEMORY.md, the project's PROCESS.md headings, open gates |
| `harness plan new\|save\|show\|review\|approve\|reject` | Plan lifecycle. `review` starts the reviewer job and waits up to `--timeout 540`. `approve` is refused until the review is finished, unless `plan.review_max: 0`. `quick` plans skip review: the user's check of the ticket list is their approval. |
| `harness ticket add\|show\|list\|find\|set\|move\|changes` | Ticket lifecycle. `add --plan <id>` validates the schema, acyclic `depends_on` and caps, and is refused unless the plan is approved. `changes` lists per-file diffs with the model and loop that wrote them. |
| `harness next [project]` | Runnable tickets |
| `harness run <id>… [--steps N]` | Claim tickets (→ `in_process`), start detached workers, return at once |
| `harness wait [project] [--timeout 540]` | Block until a ticket or plan needs the conductor: `done`, `needs_approval`, `stalled`, `failed`, `awaiting_merge`, plan review finished |
| `harness approve\|park\|stop\|pause\|resume\|merge` | Gates and controls |
| `harness memory add\|compact\|show` | Memory writes, attributed in the journal |
| `harness status [project]` | Board summary; how a fresh conductor picks up where another stopped |
| `harness init\|doctor\|link\|adopt` | Links and repair (§4.2) |
| `harness skills install\|lint\|eval` | Packaging (§8) |
| `harness ui [open\|stop]` | Local UI (§9) |

`harness next` orders round-robin across projects, then by importance (critical first), then by age. A ticket is runnable when every `depends_on` ticket is done, its `touches` do not overlap any `in_process` ticket of the same project (two paths overlap when one is a prefix of the other, compared segment by segment, so `services/web` and `services/webhooks` do not; empty `touches` overlaps everything), and its next step's provider has a free slot within `sessions.max` and `sessions.per_provider`. Workers take slots per step, not per ticket.

`next` and `wait` record a conductor ping in `runtime/conductors/` (process id, agent if detectable, project filter); the UI shows these as live conductors.

### 6.1 Journal events

One JSON object per line in `journal/YYYY-MM-DD.jsonl`:

```json
{"ts":"2026-10-22T12:04:11Z","type":"step.end","project":"payments-api","ticket":"4f2a1b7c","step":"implement","role":"implementer","provider":"codex","model":"default","session":"019a…","loop":2,"verdict":"pass","tokens":{"in":12000,"out":3400,"cache_read":80000},"duration_s":252,"files":3,"added":128,"removed":14,"commit":"abc1234"}
```

Types: `plan.created`, `plan.reviewed`, `plan.approved`, `ticket.created`, `ticket.claimed`, `step.start`, `step.end`, `ticket.recirculated`, `ticket.needs_approval`, `ticket.approved`, `ticket.stalled`, `ticket.failed`, `ticket.awaiting_merge`, `ticket.merged`, `ticket.moved`, `memory.write`, `session.created`, `session.resumed`, `worker.started`, `worker.exited`, `settings.changed`, `link.broken`, `link.repaired`, `link.adopted`. Secrets are redacted before writing.

## 7. Workers and provider adapters

### 7.1 Worker lifecycle

A worker runs one job: a ticket's steps, a plan review, or a memory compaction. `harness run` claims a ticket under the project lock, moves it to `in_process`, and starts `python -m super_harness.worker <job>` in a new session (`setsid`), logging to `runtime/logs/<id>.log`. For a ticket job, each step:

1. Checks pause and stop flags, then the loop and token caps (§5).
2. Takes a provider slot, or waits as `waiting_slot`.
3. For `implement`: creates or reuses the worktree `worktrees/<slug>/hrn-<id8>` on branch `hrn/<id8>` and records the start commit.
4. Builds the prompt. A new session gets the role skill (Claude: `--append-system-prompt-file`; others: prepended to the prompt), the absolute ticket path, the step instruction and the output schema. A resumed session gets only the delta, e.g. "loop 2: fix the findings in ## Findings".
5. Calls the adapter; records session id, usage and verdict; writes `## Handoff`, `## Findings` and `## Log`; emits `step.end`.
6. For `implement`: if the agent committed, `git reset --soft <start>`; then harness commits all changes with trailers.
7. Routes (pass → next step; fail → `on_fail` target with loop + 1) and releases the slot.
8. At a gate or at the end: sets the status, emits the event, exits.

The worker heartbeats every 15 seconds. With no heartbeat for 2 minutes, the dead-worker check (part of `harness doctor`, and also run inside `next` and `wait`) marks the ticket `failed` with "worker died"; `harness run <id>` resumes it, and its sessions resume by id.

Commit trailers:

```
hrn(7b55e0c1): loop 2 implement: retry webhook delivery with backoff

Harness-Ticket: 7b55e0c1-3d42-4ab9-9f07-c81e2a6d5f10
Harness-Step: implement
Harness-Loop: 2
Harness-Agent: implementer
Harness-Model: codex/default
```

Merges are fast-forward, so the trailers survive and `git log --grep "Harness-Ticket: <uuid>"` finds a ticket's changes long after it is done.

### 7.2 Provider protocol

```python
class Provider(Protocol):
    name: str

    def detect(self) -> ProviderStatus: ...  # installed, version, signed-in state
    def run(self, req: StepRequest) -> StepResult: ...
    def attach_command(
        self, session_id: str, cwd: Path
    ) -> list[str]: ...  # "Attach to live CLI session"
```

- `StepRequest`: cwd, prompt, role skill path, model, session id (`None` = new session), JSON schema, permission profile (`read_only` | `edit_worktree`), timeout.
- `StepResult`: session id, ok, structured output, text, usage (input, output, cache read and write, cost when reported), duration, and an error kind (`auth`, `rate_limit`, `timeout`, `empty`, `schema`, `crash`) with an optional `retry_after`.
- Signed-in state comes from each CLI's own status command where one exists, otherwise from the last run's `auth` error. Token files are never read.

| Provider | New session | Resume | Notes |
|---|---|---|---|
| claude | `claude -p … --output-format json --json-schema …` | `--resume <id>` | permission profile → `--permission-mode` plus `--allowedTools`; never `--bare` |
| codex | `codex exec --json …` | `codex exec resume <id> "…"` | never `--ephemeral`; the schema flag and sandbox mapping are confirmed in the SP3 spec |
| antigravity | `agy -p … --output-format json --json-schema …` | `--conversation <id>` | empty stdout with exit 0 is an `empty` error: recover from the transcript, otherwise fail |
| gemini | `gemini -p … --output-format json` | confirmed in the SP3 spec | optional; for API-key or enterprise users |
| shell | `project.test_cmd` | — | `run_tests` steps; exit 0 = pass |

Errors: `auth` stops the ticket with "sign in to <cli> interactively"; `rate_limit` switches to the role's `fallback` when `fallback_on_rate_limit` is on, otherwise waits as `waiting_quota` until `retry_after`; `timeout` retries once; `schema` retries once with a "return valid JSON" repair prompt; anything else → `failed` with the log path.

## 8. Skills

### 8.1 Installed skills

| Skill | Invoked by | Steps |
|---|---|---|
| `to-plan-with-grill` | user | `harness context` → `harness plan new` → look up facts yourself (code, docs, memory; a subagent if the host has one) → grill rounds of at most `grill.round_size` questions, each with a recommended answer, using the host's multiple-choice tool if it has one, until nothing is left to ask and nothing is silently assumed → restate the shared understanding; the user confirms → `harness plan save` → `harness plan review` → show open findings → the user approves, edits or rejects → `harness plan approve` |
| `to-plan` | user | the same without grilling; every unasked decision becomes an `## Assumptions` line |
| `to-ticket` | user | an approved plan id, or a short prompt (creates a `quick` plan) → vertical slices: end to end, verifiable alone, one fresh context window each; wide refactors split expand → migrate → contract → importance by rubric → numbered list (title · importance · blockers · touches) → the user adjusts → `harness ticket add --plan <id>` |
| `to-loop` | user | `harness doctor --quiet` → loop: `harness next` → `harness run` → `harness wait` → act on each event (ask the user to grant loops, re-plan stalled tickets, approve merges) until nothing is runnable or the user stops |
| `open-ui` | user | `harness ui open`; on exit 4, ask to install the UI extra, install it, open |
| `harness-memory` | model | triggered when the user states a lasting preference or goal, rejects an approach, or a design decision is made → `harness memory add` |

Importance rubric (`to-ticket/references/importance.md`): critical when the slice touches auth, secrets, payments, data migrations, infrastructure or anything irreversible; standard when it spans modules or changes a public interface; simple otherwise.

Every skill's step 0 runs `harness --version`. If the command is missing or is not super-harness, the skill prints the install line and stops.

### 8.2 Role skills

`plan`, `review-plan`, `implement`, `review-code`, `review-security`, `run-tests`, `sync-docs`. They ship in `super_harness/roles/`, are seeded to `defaults/roles/`, may be overridden per project, and are injected by the worker, never installed into agents. An agent created in the UI points at a role skill file.

### 8.3 Writing standard

`harness skills lint` enforces these in CI and at install time:

- Valid Agent Skills frontmatter; `name` equals the folder name.
- `description` starts with "Use when", lists triggers only (never the steps), and stays within 500 characters.
- At most 80 lines and 400 words (`skill.max_lines`, `skill.max_words`); aim for 200 words.
- Every `harness …` command a skill mentions exists in the CLI, so skills and CLI cannot drift apart.
- References sit one level deep and are named by their trigger, e.g. "read `references/importance.md` when assigning importance".
- Each step ends on a checkable condition; output shapes are given as templates, not as lists of don'ts.

Skills are built test-first (superpowers `writing-skills`): a scenario must fail without the skill, then the smallest skill that makes it pass is written. `harness skills eval <skill> --agent claude,codex,antigravity` replays `evals/*.yaml` scenarios headless against a temporary store and asserts on store state and journal events.

### 8.4 Distribution

```
super-harness/
├── skills/<name>/SKILL.md          installable set (§8.1)
├── .claude-plugin/                 Claude plugin marketplace manifest
└── src/super_harness/              harness CLI and role skills
```

- `npx skills add <owner>/super-harness [-g]`. Claude Code gets `.claude/skills/`; Codex, Antigravity, Gemini CLI, Cursor, Copilot and OpenCode get `.agents/skills/`.
- `uv tool install super-harness && harness skills install --agent claude,codex,antigravity [--global]`, with no Node needed.
- Claude and Codex plugin marketplaces, for auto-update.

## 9. UI

`harness ui open` starts or reuses a detached FastAPI server on 127.0.0.1 with a random per-run token, opens the browser and prints the URL. The server serves prebuilt static assets, REST endpoints over `ops`, and SSE from the journal tail. It implements the seven canvas screens: Overview, Task board, Ticket detail, Workflow editor, Agents, Settings, Memory. The canvas's "loop engine running" becomes "live conductors" (§6). The frontend stack, component structure and canvas parity checklist belong to the SP5 spec.

## 10. Security

- **Credentials:** only official binaries run, under the user's login. Token files are never read and `claude --bare` is never used. `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `CODEX_API_KEY`, `GEMINI_API_KEY` and `GOOGLE_API_KEY` are removed from worker environments unless `providers.<p>.allow_api_key: true`, so work is billed to the subscription.
- **Trust:** workers run only in registered repos. `harness doctor` warns once when a repo ships agent hooks or MCP config (`.claude/settings.json` hooks, `.mcp.json`), because `claude -p` runs them without a trust prompt.
- **Least privilege:** planners and reviewers get `read_only`. Implementers get `edit_worktree`: their worktree, plus `project.test_cmd`, `project.lint_cmd` and read-only git. Permission-bypass flags (`--dangerously-skip-permissions` and equivalents) are off by default and need an explicit per-agent setting.
- **Git:** local fast-forward merges only; harness never pushes; `merge.mode: ask` by default.
- **Secrets:** journal, memory and Handoff text pass through a redactor (common key and token patterns) before they are written.
- **UI:** bound to 127.0.0.1; per-run token; Host and Origin checks against DNS rebinding and CSRF; no CORS.
- **Store and skills:** `~/.harness` is mode 0700. Skills are plain text and fetch nothing from the network; updates show a diff before install.

## 11. Testing

| Layer | How |
|---|---|
| Unit | model validation; store atomicity, locks, moves, links and adopt; scheduler (dependencies, overlap, slots, fairness); workflow routing (loops, caps, stalls, hitl) |
| Adapter contract | fake `claude`, `codex` and `agy` executables on PATH replay recorded JSON fixtures, so CI uses no subscription |
| Integration | temporary `HARNESS_HOME` and git repo; full lifecycle with fakes: plan → implement → review fails → implement → pass → merge |
| Live smoke (opt-in, `-m live`) | one simple ticket per real provider on a scratch repo; catches CLI flag drift |
| Skills | `harness skills lint` in CI; `harness skills eval` live, opt-in |
| UI | API tests with FastAPI TestClient; frontend tests in SP5 |

Test commands are quiet on success and print only failures.

## 12. Sub-project 1: Foundation

### 12.1 Deliverables

```
super-harness/
├── AGENTS.md                 canonical agent instructions, router style, at most 100 lines
├── CLAUDE.md                 the /init prefix plus "@AGENTS.md"
├── GEMINI.md                 "@AGENTS.md"
├── README.md                 for humans: what it is, install, quick start; grows with each sub-project
├── LICENSE                   MIT
├── pyproject.toml            uv, hatchling, Python ≥3.12, Typer; console scripts harness and hrn
├── Makefile                  setup · fmt · lint · type · test · docs · check
├── .pre-commit-config.yaml   ruff, docs sync, Markdown caps
├── .github/workflows/ci.yml  make check on push and pull request
├── src/super_harness/
│   ├── __init__.py           __version__
│   └── cli.py                Typer app: --version, --help
├── tests/test_cli.py
├── scripts/
│   ├── check_docs_sync.py    fails when a module changes without its doc
│   └── check_md_caps.py      enforces instruction-file and doc caps
└── docs/
    ├── README.md             index: one line per doc, plus when to read it
    ├── architecture.md       system map, kept current
    ├── conventions/
    │   ├── instruction-files.md
    │   ├── skills.md
    │   └── memory-files.md
    ├── modules/<module>/README.md   one per module
    └── superpowers/{specs,plans}/
```

- The current CLAUDE.md content moves into AGENTS.md and `docs/architecture.md`; CLAUDE.md keeps only the prefix and the import.
- `hrn` is an alias for `harness`, for machines where another `harness` (e.g. Harness.io's CLI) comes first on PATH. `harness skills install --cli-name hrn` rewrites the skills' command prefix, and `harness doctor` reports the clash.
- Module docs (`docs/modules/<m>/README.md`) have four sections: Purpose · Interface · Invariants · Changes (newest first, at most 20 lines). `check_docs_sync.py` fails when `src/super_harness/<m>/` or `<m>.py` changes in a commit range while its doc does not. A module gets its doc when it is created, so Foundation ships only the `cli` doc.
- Codex reads AGENTS.md natively. Foundation checks which context file `agy` reads and adds a pointer only if it does not read AGENTS.md.

### 12.2 Conventions to write

- `instruction-files.md`: entry files are routers (at most 100 lines and 15 hard rules; each link says when to read it); topic docs run 50–150 lines; every non-obvious rule says why and when it applies; nothing repeats what code or config already says; instructions are phrased positively; referenced commands are quiet on success.
- `skills.md`: §8.3.
- `memory-files.md`: the §4.5 table and line formats, including who writes what.

`scripts/check_md_caps.py` enforces AGENTS.md ≤ 100 lines and docs ≤ 150 lines; specs and plans are exempt.

### 12.3 Acceptance

- [ ] `make setup && make check` passes on a fresh clone on Linux and macOS.
- [ ] `uv run harness --version` and `uv run hrn --version` print the version.
- [ ] AGENTS.md has at most 100 lines; CLAUDE.md and GEMINI.md import it; a Codex session and an `agy` session started in the repo both see its rules (manual check, recorded in the plan).
- [ ] `check_docs_sync.py` fails on a deliberate undocumented module change and passes once the doc is updated.
- [ ] `check_md_caps.py` fails on an oversized doc.
- [ ] CI runs `make check` and is green.

## 13. Roadmap

| Sub-project | Scope | Exit criteria |
|---|---|---|
| 2 Store + CLI | `model`, `store`, `settings`, `memory`, `journal`, `ops` (store-only use cases); init, doctor, link, adopt; plan, ticket, memory, status and context commands | plans and tickets fully manageable from the CLI; links survive project moves; adopt merges correctly |
| 3 Engine | `adapters`, `workflow`, `scheduler`, `gitops`, `worker`; next, run, wait, approve, merge; compaction job | integration lifecycle green with fakes; live smoke green per provider |
| 4 Skills | six installed skills, seven role skills, installer, plugin manifests, lint, eval | evals pass on claude, codex and agy |
| 5 UI | FastAPI, SSE, seven screens; `open-ui` | canvas parity checklist complete; live updates; every action goes through `ops` |
