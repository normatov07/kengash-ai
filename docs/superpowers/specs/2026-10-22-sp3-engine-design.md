# Sub-project 3: Engine — Spec

- Date: 2026-10-22
- Status: approved by default (user prefers momentum; assumptions listed in §2 for veto)
- Implements: system spec `2026-10-22-super-harness-design.md` §5 (loop semantics), §6 (`next`, `run`, `wait`, gates and controls, `plan review`, `ticket changes`, `memory compact`), §7 (workers and provider adapters); units `workflow`, `scheduler`, `adapters`, `gitops`, `worker`, and their `ops` use cases.
- This spec only adds what the system spec leaves open. The system spec changes it needs (§2) were made in the same commit.
- CLI facts were checked on 2026-10-22: claude 2.1.308 and agy 1.4.5 with short real runs; codex 0.161.0 through `--help` only, because it is not installed or signed in on the dev machine. Permission rows re-checked on 2026-10-23 with claude 2.1.309 and agy 1.4.5 (M2).

## 1. Milestones

Each milestone is planned just before it is built (`docs/superpowers/plans/`), ends green on `make check`, and is reviewed against this spec.

| # | Milestone | Delivers | Exit |
|---|---|---|---|
| M1 | Engine rules | model additions (§4), `workflow`, `scheduler`, slot and flag files in `store`, `ops.queue.next_tickets`, CLI `next`, import contracts | unit tests cover every row of §6 and every `next` rule; `harness next` filters and orders tickets |
| M2 | Providers and git | `adapters` (claude, codex, antigravity, shell), fake CLIs with fixtures, `gitops`, provider and trust checks in `doctor` | adapter contract tests pass against the fakes; git operations pass on temporary repos |
| M3 | Workers and controls | `worker`, step execution in `ops`, `run`, `wait`, `approve`, `park`, `stop`, `pause`, `resume`, `merge`, `ticket changes`, `ticket attach`, dead-worker check, conductor pings | the integration lifecycle (§10) passes with detached workers and fake CLIs |
| M4 | Plan review, compaction, live | `plan review`, `memory compact`, DECISIONS archive, live smoke tests | live smoke green for every provider installed and signed in on the dev machine (claude and agy today; codex once installed) |

## 2. Decisions (assumed defaults — veto any)

1. **`worker` imports `ops`.** The worker is a frontend for detached jobs, as `cli` is for commands: `python -m super_harness.worker` parses its job, heartbeats and calls `ops`. `ops` never imports `worker`; it starts it as a process. Merge, queue refresh and gate handling then live once, in `ops`. (System spec §3.1 changed.)
2. **Worktree at claim.** `harness run` creates or reuses the ticket's worktree before the first step, and every step of the ticket runs in it: all roles see the same code, and every CLI resumes its session from the directory that created it. (§7.1 changed.)
3. **Context inline.** Prompts carry the ticket's Scope, Acceptance, latest Handoff and open Findings, plus the plan's Goal. Agents never read or write store files. (§7.1 changed.)
4. **Workers skip the user's personal agent setup.** A default `claude -p` loaded the user's 6 plugins, 7 hooks and 5 MCP servers (Gmail and Drive among them); with `--setting-sources project,local --strict-mcp-config` it loaded none of them. Workers therefore run claude with those flags, codex with `--ignore-user-config`; agy gets no isolation flag, because `--disable-slash-commands` voids `--mode`. The repo's own AGENTS.md, CLAUDE.md and project settings still apply. `providers.<p>.user_config: true` opts back in.
5. **Session ids are known before a step ends.** New claude sessions get `--session-id <uuid>` chosen by harness; codex prints its id first (`thread.started`); agy returns it at the end. A killed claude or codex step resumes its session; a killed agy step starts the role's session again.
6. **Dependencies are met by `done/merged` and `done/closed` only.** `done/branch_ready` keeps dependents blocked until the branch is merged or the ticket closed, because a dependent's worktree starts from the base branch. (SP2 decision 16 and system spec §4.4, §6 changed.)
7. **Fallback covers unavailable providers.** A role's `fallback` list is used when its provider is not installed or not signed in, and on rate limits while `fallback_on_rate_limit` is on. With no usable provider, `run` exits 4 naming the install or sign-in step.
8. **Controls.** `park ID --why W` → `in_queue/parked`; a running worker finishes its step first. `stop ID` kills the worker now (SIGTERM to its process group, SIGKILL after 10 s) → `in_process/failed` "stopped". `pause [--project P]` lets running steps finish, then leaves their tickets at the new sub-status `in_process/paused` and starts nothing new in scope; `resume [--project P]` clears the pause and restarts them. `run ID` also resumes `failed`, `stalled` and `paused` tickets at their current step, and resuming a stalled ticket clears its stall streaks. (`paused` added to system spec §4.4.)
9. **`wait` reports each event once per scope.** It returns events newer than the previous `wait` for the same project filter (cursor in `runtime/conductors/`); a scope's first `wait` reports every open gate. It returns `idle` at once when nothing in scope is running.
10. **Tokens.** A step adds input plus output tokens to `tokens`; cache reads and writes are journaled, not counted. Tickets get `tokens_max` (empty = `tokens.per_ticket_max`); approving at the token cap adds `tokens.per_ticket_max`, or `--tokens N`.
11. **Engine bookkeeping lives in `runtime/`** (not versioned): stall streaks, ticket `review_plan` rounds, the reason a ticket waits for approval, worker records, slots, flags, wait cursors, conductor pings and last-claim times. Losing it restarts stall counting and nothing else.
12. **Commits in the user's repo** use the user's git identity, signing and hooks. A failing hook gives the step's session one repair turn with the hook output; a second failure fails the ticket with the output's last lines.
13. **Merge** works from `in_process/awaiting_merge` and `done/branch_ready`; a rebase conflict sends the ticket back to `implement` with loop + 1 (exit 1).
14. **Plan review.** The reviewer is the `plan-reviewer` agent. With `plan.reviewer: different-provider`, when that agent's provider equals the conductor's (`--by`, which defaults to `$HARNESS_AGENT`, else `claude` when `CLAUDECODE=1`), harness takes its first fallback on another provider, else the first other signed-in provider. `plan.reviewer: <provider>[/model]` names it directly. Rounds resume one reviewer session, kept in the plan as `review.session`. `plan approve` accepts a passing verdict, used-up rounds (the user overrides a fail), `plan.review_max: 0`, a quick plan, or `--skip-review` (the user's explicit override, journaled).
15. **Compaction** runs on `memory.compactor` (new setting, default `claude/haiku`). `memory add` starts it in the background when MEMORY.md passes `memory.compact_at_lines`; `harness memory compact` runs it and waits. When `memory add --decision` takes DECISIONS.md past 300 lines, its oldest lines move to `memory/archive/DECISIONS.md`, without a model.
16. **No gemini adapter in SP3.** Gemini is optional (system spec D10), is not installed on the dev machine, and its consumer login closed on 2026-06-18. An agent set to `gemini` makes `run` exit 4; the `Provider` protocol keeps it a small later addition. (§7.2 changed.)
17. **Slots** are counted machine-wide against the defaults scope's `sessions.max` and `sessions.per_provider`, and per project against that project's values. Waiting workers take freed slots in arrival order.
18. **Sandboxed conductors.** `harness run` exits 4 when `CODEX_SANDBOX_NETWORK_DISABLED=1`, because workers started from a network-less codex sandbox cannot reach any provider. SP4 documents conductor setup.
19. **Permission bypass** is per agent: `agents.<role>.bypass_permissions: true` adds the CLI's bypass flag (system spec §10); default false.
20. **Commits after every editing step** (`implement`, `docs`), each with its own `Harness-Step` trailer.
21. **Claims count queued slots.** `run` re-checks overlap and slots under the locks, counting held and queued slots, and queues the claimed ticket's first slot, so two conductors cannot overbook a provider.
22. **Stopping.** `run` writes `workers/<id>.json` before it returns. A worker never writes a stopped state: `stop` waits for it to exit, then marks the ticket `failed` "stopped" and frees its slots.
23. **Merge conflicts** send the ticket to `in_queue/ready` at `implement` with loop + 1 (at the loop cap: `needs_approval`), with a finding listing the conflicted files; the conductor runs it again.
24. **`wait` events** are the journal events `ticket.needs_approval`, `ticket.stalled`, `ticket.failed`, `ticket.awaiting_merge`, `ticket.merged`, and `ticket.moved` into `done/`; each carries `status`, `loop`, `loop_max` and `reason`. The cursor is a journal position (day file and line).
25. **Resumed sessions** get the open Findings on work steps, and the latest Handoff plus the diff stat on review steps. `## Findings` holds the latest review step's findings; a pass clears it.
26. **The user wins.** When a ticket leaves `in_process` (or changes step) while its worker runs, the worker drops the step's result, frees its slot and exits.
27. **Deferred park.** `park` on a running ticket prints `ticket <id> → in_queue/parked after its step`; the worker parks it before its next step.
28. **Plan review job.** `harness plan review` refreshes `review.max` from `plan.review_max`, picks the reviewer (decision 14), records it as `review.reviewer`, sets the plan `in_review`, starts `python -m super_harness.worker plan-review <id>` and waits for that round's `plan.reviewed` event (or the job's `worker.exited`) up to `--timeout`. A timed-out review keeps running; `plan review` again waits for it; a round that already has a verdict is reprinted, never rerun. A round counts only once it has a verdict. A fail at round `review.max`, or a call after it, exits 5: the user approves (overriding) or rejects. `plan save` sets the plan back to `draft` and keeps the round count. `plan.review_max: 0` makes `plan review` an error.
29. **Plan review rounds** run read-only in the project's main working tree. A new session gets the role skill, the plan's sections (all but the Review log) and the newest 40 project and global DECISIONS.md entries; a resumed round gets the plan again plus its Review log. Findings append to the Review log as `- round <r> · <severity> · <file>:<line> · <issue> · <fix>`, a pass as `- round <r> · pass · <summary>`. Rounds take a slot like steps; a timeout and a schema error each retry once; any other error, or a plan changed during the round, ends the job without a round (`worker.exited`, `ok: false`). With `different-provider` and no other usable provider, the review runs on the conductor's provider and `plan review` warns.
30. **Plan approval** is refused (exit 5) while the latest round failed and rounds are left, unless `--skip-review`.
31. **Compaction job.** `python -m super_harness.worker compact` (one at a time; worker id `compact`) runs `memory.compactor` read-only in `memory/`, a new session each time, asking for at most ¾ of `memory.compact_at_lines` lines and keeping the title, intro, every `##` heading and every entry marked `(pin)` verbatim. Lines added while it ran are merged back into their sections; the result is accepted only with fewer lines than `memory.compact_at_lines`, every heading and every pinned entry (a `- ` line containing `(pin)`). Accepted: MEMORY.md is replaced and committed. Either way `memory.compacted` is journaled with `before`, `after`, `accepted` and `reason`. `memory compact` exits 1 on a rejection. `memory add` starts the job when MEMORY.md passes the cap, unless it runs already.
32. **DECISIONS archive.** When `memory add --decision` takes DECISIONS.md past 300 lines, its oldest entries move, oldest first, to `memory/archive/DECISIONS.md` until it has 300 lines again; the `memory.write` event counts them (`archived`).
33. **Job workers.** Plan-review and compaction workers write `workers/<id>.json` with their `job`, heartbeat like ticket workers, and journal `worker.exited` (`job`, `ok: false`, `reason`) when they fail. The dead-worker check drops a dead job's record, frees its slot and journals `worker.exited` "worker died". `wait` reports `plan.reviewed` events, a reviewed plan awaiting approval counts as an open gate, and a running plan review counts as running work.
34. **Resuming a stalled ticket** clears its stall streaks and its failing `review_plan` rounds.
35. **Live smoke** runs with `uv run pytest -m live` (or `make live`), never in `make check`. For each provider installed and signed in: one ticket through plan → implement → review_code → merge, one plan-review round and one compaction, on claude `haiku`, agy `gemini-3.8-flash-low` or codex's default (`HARNESS_LIVE_<PROVIDER>_MODEL` overrides).

## 3. Units

| Unit | Holds | May import |
|---|---|---|
| `workflow` | pure routing: effective steps, outcomes, loop and token caps, stalls, hitl, end routing (§6) | `model` |
| `scheduler` | pure decisions: runnable set, `touches` overlap, slot fit, project turns (§7) | `model` |
| `adapters` | `Provider` implementations, process runner with timeouts and process-group kill, environment scrubbing (§8) | `model` |
| `gitops` | git commands for worktrees, commits, diffs, rebase, merge (§9) | `model` |
| `store` (adds `runtime`) | worker records, slots, flags, per-ticket engine state, wait cursors, conductor pings | `model` |
| `ops` (adds `queue`, `steps`, `controls`, `merging`, `waiting`, `reviews`, `compaction`, `changes`, `providers`) | use cases; wires IO around the pure units | everything except `cli`, `worker`, `ui` |
| `worker` | `python -m super_harness.worker ticket\|plan-review\|compact <id> [--steps N]`; heartbeat thread; signal handling | `ops`, `model` |

Import-linter layers become `cli | worker > ops > memory > journal | settings > store > model`; `workflow`, `scheduler`, `adapters` and `gitops` import only `model`; `cli` and `worker` reach the store only through `ops`.

## 4. State

Ticket and plan fields (system spec §4.4):

- `step`: the step running or next to run; set at claim, kept while a ticket is parked or requeued so it resumes there, cleared once it is done.
- `tokens_max`: empty means `tokens.per_ticket_max`.
- Plan `review.session`: `{provider, model, id}` of the reviewer session, empty before the first review.
- Sub-status `in_process/paused`.

Settings (system spec §4.6): `memory.compactor: claude/haiku`; `providers.<p>.allow_api_key: false`, `providers.<p>.user_config: false`; `agents.<role>.bypass_permissions: false`.

```
runtime/                       (git-ignored)
├── locks/                     <slug>.lock · git.lock · slots.lock · repo-<slug>.lock
├── workers/<id>.json          job, pid, step, started, heartbeat (every 15 s)
├── slots.json                 held slots (provider, project, ticket, step, pid, since) and waiters in arrival order
├── claims.json                last claim time per project (project turns in `next`)
├── trust.json                 digest of each repo's hook and MCP files doctor last reported
├── flags/                     pause · pause-<slug> · park-<id>
├── tickets/<id>.json          stall streaks, review_plan rounds, approval reason, implement start commit; for plan ids and the compaction job: call count and reviewer totals
├── conductors/                <pid>.json pings (pid, agent, project filter, time) · cursor-<scope>.json
├── schemas/<name>.json        output schemas for `codex --output-schema`
└── logs/                      <id>.log per worker · <id>-<n>.out raw CLI output per step attempt
```

A worker is dead when its heartbeat is older than 2 minutes or its pid is gone. `next` and `wait` mark its ticket `in_process/failed` "worker died"; `doctor` reports it and marks it with `--fix`.

## 5. Step execution

A ticket job runs steps until a gate or the end. Each step:

1. Under the project lock: reload the ticket; exit at a pause or park flag or a spent `--steps` budget (→ `in_process/paused` or `in_queue/parked`); ask `workflow` for the step and the caps; a cap → gate and exit.
2. Resolve the step's agent: role → `cli` provider and model, then `fallback` (decision 7); `shell` for `run_tests`.
3. Take a slot (`scheduler` decides, `store` persists under `slots.lock`; shell steps need none). Without one the ticket shows `waiting_slot` and the worker polls every 5 s. A worker waiting for quota sleeps until `retry_after`, still heartbeating.
4. Set the status to the step's `status.names` value; journal `step.start`, then `session.created` or `session.resumed`.
5. Build the request (§8.2) and run the adapter with `step_timeout_min`. `timeout` and `schema` errors retry once; `rate_limit` → fallback, else `waiting_quota` until `retry_after` (15 minutes when the CLI names no time); `auth` → `failed` "sign in to <cli> interactively"; other errors → `failed` with the log path.
6. After an editing step: `git reset --soft <start>` when the agent committed, then commit everything with trailers (system spec §7.1).
7. Under the project lock: write `## Handoff` (work steps) or `## Findings` (review steps), append `## Log`, add tokens, store the session, journal `step.end` (system spec §6.1 fields, plus finding fingerprints); route with `workflow`; release the slot; commit the store.

## 6. Workflow rules

Effective steps are the workflow's steps, minus steps whose role is off (a `blocking` role that is off fails the ticket: "role <r> is off and blocking") and minus `review_plan` when `plan.review_max: 0`, plus `approve` after `plan` for `gate: hitl` tickets (first, when there is no `plan` step). Steps `plan`, `review_plan`, `review_code` and `security` run `read_only`; `implement` and `docs` run `edit_worktree`; `run_tests` runs `project.test_cmd`.

| Situation | Decision |
|---|---|
| before a step, `tokens ≥ tokens_max` | `needs_approval` (token cap) |
| step `approve` | `needs_approval` until `harness approve` |
| pass, more steps | next step |
| pass, last step, `merge.mode: ask` or `gate: hitl` | `awaiting_merge` |
| pass, last step, `auto` | merge now when the main working tree is clean and on the base branch, else `awaiting_merge` |
| pass, last step, `branch` | `done/branch_ready` |
| fail on `review_plan`, the ticket's failing rounds reaching `plan.review_max` | `stalled` |
| a fingerprint failing `stall_repeat` loops in a row | `stalled` |
| fail on `review_plan` with `loop_count_rejected_review: false` | target step, same loop (never hits the loop cap) |
| fail with an `on_fail` edge, `loop < loop_max` | target step, `loop + 1` (`ticket.recirculated`) |
| fail with an edge, `loop = loop_max` | `needs_approval` (loop cap), or `in_queue/parked` when `loop_ask_at_cap: false` |
| fail without an `on_fail` edge | `failed` |

Rows are checked top to bottom; the first match decides. A fingerprint is the first 12 hex digits of the SHA-1 of the finding's normalised file path plus its issue text, lowercased, with each run of digits replaced by `0` and each run of whitespace by one space. Approving a loop cap raises `loop_max` by `--loops N` (default `loop_grant`) and recirculates; approving a token cap raises `tokens_max`; approving an `approve` step passes it. Approval restarts the worker at once.

## 7. Scheduling

`harness next` lists `in_queue/ready` tickets (dependencies merged or closed) whose `touches` overlap no `in_process` ticket of the same project nor any ticket listed before them, and whose first step's provider (after fallback) fits a free slot. Paths overlap when one is a prefix of the other segment by segment; empty `touches` overlaps everything. Projects take turns, the one with the oldest last claim first; within a project, critical before standard before simple, then oldest first. Nothing in a paused scope is runnable. `run` checks the same rules again under the locks, so two conductors cannot claim one ticket.

## 8. Provider adapters

### 8.1 Command lines

| | claude | codex | antigravity (`agy`) |
|---|---|---|---|
| new session | `claude -p <prompt> --output-format json --json-schema <json> --session-id <uuid> [--model M] [--append-system-prompt <role skill>]` | `codex exec --json --output-schema <file> -s <sandbox> [-m M] <prompt>` | `agy -p <prompt> --output-format json --json-schema <json> [--model M] --mode <mode>` |
| resume | `claude -p <delta> --resume <id> --output-format json --json-schema <json>` | `codex exec resume --json --output-schema <file> -c sandbox_mode="<sandbox>" [-m M] <id> <delta>` (resume takes no `-s` or `-C`) | `agy -p <delta> --conversation <id> --output-format json --json-schema <json> --mode <mode>` |
| `read_only` | `--permission-mode dontAsk --allowedTools Read Grep Glob "Bash(git diff:*)" "Bash(git log:*)" "Bash(git show:*)" "Bash(git status:*)"` | sandbox `read-only` | `--mode plan` |
| `edit_worktree` | `--permission-mode acceptEdits --permission-prompts none --allowedTools` the read set plus `"Bash(<test_cmd>:*)" "Bash(<lint_cmd>:*)"` | sandbox `workspace-write` | `--mode accept-edits` |
| isolation (default) | `--setting-sources project,local --strict-mcp-config` | `--ignore-user-config` | none (see below) |
| bypass (opt-in) | `--dangerously-skip-permissions` | `--dangerously-bypass-approvals-and-sandbox` | `--dangerously-skip-permissions` |
| output | one JSON object: `session_id`, `is_error`, `subtype`, `structured_output`, `result`, `usage`, `total_cost_usd`, `api_error_status` | JSONL: `thread.started` (`thread_id`), `item.completed` with an `agent_message` whose text is the schema JSON, `turn.completed` (`usage`: input, cached input, output, reasoning), `turn.failed`, `error` | one JSON object: `conversation_id`, `status` (`SUCCESS`), `response`, `structured_output`, `usage` (input, output, thinking, cache read), `denied_actions`; `usage` and `num_turns` are conversation totals |
| signed in | `claude auth status --json`: `loggedIn`; `authMethod` reveals API-key logins | `codex login status`: exit 0, else "Not logged in" and exit 1 | `agy models` exits 0 |
| attach | `claude --resume <id>` | `codex resume <id>` | `agy --conversation <id>` |

Profile, isolation and bypass flags go on every call, new or resumed (codex resumes take the sandbox as `-c sandbox_mode=…`), and so does the model when the agent names one. Every CLI runs with the worktree as its working directory, in its own process group, stdout to `runtime/logs/<id>-<n>.out`. Workers drop `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `CODEX_API_KEY`, `GEMINI_API_KEY` and `GOOGLE_API_KEY` (unless `providers.<p>.allow_api_key`) and the conductor markers `CLAUDECODE` and `CLAUDE_CODE_ENTRYPOINT`, and set `HARNESS_AGENT=<role>`. Never used: claude `--bare` and `--no-session-persistence`, codex `--ephemeral`.

- agy repeats the previous turn's `structured_output` when a turn ends without schema JSON, even with the schema passed: the output counts only when `response` (often prose, then the JSON on its last line) holds a line that parses to the same JSON, else `schema`. Every agy turn still passes the schema.
- agy read-only steps run `--mode plan` and end the prompt with: `This is a read-only step: read files with your file-viewing tools only; never run terminal commands.` A turn with `denied_actions` and no output is `empty`, naming the denied actions.
- Token fields: `input` excludes cache reads (codex counts them inside `input_tokens`, so the adapter subtracts; agy reports them apart, and they can exceed `input_tokens`); `output` includes thinking. agy reports conversation totals: the adapter subtracts the totals after the session's previous turn (`StepRequest.prior_usage`) and returns the new totals (`StepResult.total_usage`).
- `allow_api_key` keeps only that provider's variables: claude `ANTHROPIC_API_KEY`; codex `OPENAI_API_KEY`, `CODEX_API_KEY`; antigravity `GEMINI_API_KEY`, `GOOGLE_API_KEY`. The bypass flag replaces the permission-profile flags for claude and codex; agy keeps `--mode`. Prompt and skill text never start with `-` in argv (a newline is prepended), and a prompt over 120 KiB fails as `crash` before the CLI starts. New claude sessions get their `--session-id` from harness, so a killed step can resume.
- `--ignore-user-config` also drops the user's codex model default and any credential-store setting; if codex then reports a sign-in error, `providers.codex.user_config: true` restores both.
- Error kinds: claude `api_error_status` 401 or 403 → `auth`, 429 or a usage-limit `result` → `rate_limit` (reset time parsed when given); codex `turn.failed` and `error` messages; agy a `status` other than `SUCCESS`; exit 0 with no output → `empty`; output that fails the schema → `schema`; killed at the timeout → `timeout`; anything else → `crash`. Exact strings come from recorded fixtures, and live smoke re-checks them.
- claude's `dontAsk`, `acceptEdits --permission-prompts none` and the agy rows were confirmed by live runs on 2026-10-23; the M4 live smoke re-checks them.
- `shell` runs `sh -c <project.test_cmd>` in the worktree: exit 0 passes; otherwise one finding holds the last 20 output lines. An empty `test_cmd` fails the step with "set project.test_cmd".

### 8.2 Prompts and outputs

Output schemas are strict (every field required, no extra fields), so all three CLIs accept them:

- Work steps (`plan`, `implement`, `docs`): `{summary, handoff}`; harness keeps the first 15 handoff lines.
- Review steps (`review_plan`, `review_code`, `security`) and plan review: `{verdict: pass|fail, summary, findings: [{severity: high|medium|low, file, line, issue, fix}]}`; a fail without findings is a `schema` error.
- Compaction: `{text}`, the whole new MEMORY.md.

A new session gets the role skill (project `roles/` → `defaults/roles/` → package; none until SP4 ships them; claude through `--append-system-prompt`, others prepended), then:

```
You are the <role> for ticket <id> "<title>", loop <n> of <max>, step <step>.
<step instruction>
## Goal (plan <plan id>)   ## Scope   ## Acceptance   ## Handoff   ## Findings   (inline, empty ones left out)
Reply with JSON that matches the schema.
```

A resumed session gets only `Loop <n>, step <step>: <step instruction>` plus the Handoff or Findings written since its last turn. Review steps get `git diff --stat <base>...HEAD` inline and read the full diff with read-only git (`review.diff_only`). Step instructions are one line each, kept in `ops`.

## 9. Git operations

- Worktree: `git worktree add -b hrn/<id8> <store>/worktrees/<slug>/hrn-<id8> <base>`; reused when it exists; re-attached when only the branch is left.
- Commit: `git add -A`, then a commit `hrn(<id8>): loop <n> <step>: <summary's first line>` with the trailers of system spec §7.1.
- Diffs: `git diff <base>...HEAD` and `--numstat`. `ticket changes` reads the commits carrying `Harness-Ticket: <uuid>` on the ticket branch, or on the base branch after the merge.
- Merge: rebase onto the base branch inside the worktree (a conflict aborts the rebase and records a finding listing the files), `git merge --ff-only hrn/<id8>` in the main working tree (refused unless clean and on the base branch), then remove the worktree and delete the branch.
- `repo-<slug>.lock` serialises worktree, rebase and merge commands per repo.

## 10. Commands

| Command | Output (default) | Exit codes |
|---|---|---|
| `harness next [--project P]` | `<id> <project> <importance> <step>→<provider> <title>` per ticket, at most 5, then `+N more`; or `nothing runnable: ` with the non-zero counts of held-back, blocked, running, gated and paused tickets (`the queue is empty` when all are zero) | 0 |
| `harness run ID… [--steps N]` | `started <id> <step>→<provider>` or `skipped <id>: <reason>` per ticket | 0 · 1 none started · 4 provider missing or signed out, sandboxed conductor |
| `harness wait [--project P] [--timeout 540]` | `<id> <status> loop n/max: <detail>` per event, or `idle` | 0 · 3 timeout |
| `harness approve ID [--loops N] [--tokens N]` | `ticket <id> approved; running` | 0 · 1 not waiting for approval |
| `harness park ID --why W` · `harness stop ID` | `ticket <id> → in_queue/parked` · `ticket <id> stopped` | 0 · 1 |
| `harness pause\|resume [--project P]` | `paused: N running finish their step` · `resumed N` | 0 |
| `harness merge ID` | `merged <id>: N commits into <base>` | 0 · 1 main tree dirty or off base, or conflict (sent back) |
| `harness plan review ID [--timeout 540]` | `plan <id> round r: pass\|fail, N findings`, then the findings | 0 · 3 timeout · 5 rounds used up |
| `harness ticket changes ID [--diff]` | `<path> +a -r  loop n <step> <provider>/<model>` per file and commit | 0 · 1 |
| `harness ticket attach ID [--role R]` | the command that opens the role's session in its worktree | 0 · 1 no session |
| `harness memory compact [--timeout 540]` | `MEMORY.md N → M lines` | 0 · 1 result rejected · 3 timeout |
| `harness doctor` (additions) | dead workers (M3); providers of enabled agents and the compactor that are missing, signed out or unsupported (a problem when a role has no usable fallback, else a warning); a claude login other than claude.ai (warning); repo hooks or MCP config (warning, once per repo until the files change) | as in SP2 |

`next` and `wait` write a conductor ping: the nearest ancestor process named `claude`, `codex` or `agy` (else the parent), the agent (`$HARNESS_AGENT`, else detected), the project filter and the time.

## 11. Testing

- Fake CLIs (`tests/fakes/bin/claude`, `codex`, `agy`) replay fixtures in the order a test queues them, record argv and working directory, and can edit files in the worktree, so tests assert on flags, session reuse and tokens.
- Fixtures are recorded from real runs (claude and agy on 2026-10-22); codex fixtures follow the documented sample events until a real run replaces them.
- Unit: every row of §6; scheduler rules of §7; adapters (command lines per profile, output parsing, error kinds, environment); gitops on temporary repos.
- Integration: a temporary `HARNESS_HOME` and git repo with the fakes on `PATH`; `run` starts a real detached worker and the test drives `wait` through plan → implement → review fails → implement → pass → merge.
- Live smoke (`-m live`, skipped when a CLI is missing or signed out): one simple ticket per provider on a scratch repo, every agent on that provider's cheapest model.

## 12. Acceptance (SP3 exit)

- [x] `harness next` lists only runnable tickets (§7) in the right order. (M3)
- [x] `harness run` returns at once; its worker outlives the calling shell; `harness wait` returns once per gate, and `idle` when nothing runs. (M3)
- [x] The integration lifecycle passes with fakes; commits carry trailers, and `git log --grep "Harness-Ticket: <uuid>"` finds them after the merge. (M3)
- [x] Loop cap, token cap, stall, hitl approval and blocking roles behave as §6; `approve --loops` continues the ticket. (M3)
- [x] Each ticket×role session is created once and resumed at every later step (S5); every `step.end` records provider, model, session, tokens, duration and verdict (S4). (M3)
- [x] A killed worker is detected within 2 minutes, and `run` resumes its ticket with its sessions. (M3)
- [ ] `plan review` runs rounds up to `plan.review_max`; `memory compact` keeps every pin and stays under the cap.
- [ ] Live smoke green for claude and agy; codex once installed and signed in.
- [x] `make check` (with the new import contracts) green; module docs for `workflow`, `scheduler`, `adapters`, `gitops`, `worker`. (M3)
