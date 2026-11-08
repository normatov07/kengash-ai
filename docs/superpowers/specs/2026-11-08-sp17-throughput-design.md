# SP17: Throughput, steering, verified context, and per-agent models

Status: approved in chat 2026-11-08 (user: "build all of A, B, C"; models configurable on the Agents page; careful context passing). Decisions marked *(call)* are the builder's.

## 1. Why

Live `chess-samurai` loop, 2026-11-08: 139 minutes, 0 commits, 0 merges.

| Evidence | Number |
|---|---|
| One implement step killed at 30 min, same prompt, killed at 30 min | 60 min lost |
| No conductor awake after a failed ticket | 39 min lost |
| A ticket waiting for another's paths (3 shared, 1 of them generated) | 44 min |
| Last attempt: `manage_task` polls of a background test run | 79 of 176 turns |
| Whole-suite runs inside one attempt | 5 finished, 1 killed |
| agy time in model turns vs tools | 85% vs 15% |
| Tool calls per model turn | 0.97 |
| Reads as a share of tool calls | 66% |
| Workers running when busy (11-08) | mean 1.2 of 15 slots |
| Share of the Claude spend on reviews | 62% |

Not the problem: in-step checks (SP15 took `run_tests` send-backs from 22 to 0); the model tier (flash-high 9.2 s per turn, flash-medium 8.2 s).

## 2. Goals and non-goals

Goals: a stuck agent gets corrected instead of killed; finished work starts the next work without a live conductor; tickets stop waiting on each other for nothing; fewer model turns; cheaper reviews; every model choice editable on the Agents page; context that agents pass on is exact and marked for freshness.

Non-goals: a daemon (rule 7); parallel writers inside one ticket; API keys; agent-to-agent chat (user turned it down in SP13).

Anti-goals: lower quality to gain speed. kengash still runs the full suite after every editing step and before every merge.

## 3. Design

### 3.1 Steering (A1)
A headless CLI takes no input mid-turn, so kengash stops the turn and resumes the session with a correction.

`adapters/watchdog.py` reads the stream line by line during the call. Each adapter maps its events to `edit`, `poll` or `run <command>`. It stops the process for one of:

- `poll`: `steering.poll_max` (8) polls of a background command with no edit between them;
- `full runs`: the project's `test_cmd`, also wrapped, piped or redirected, run more than `steering.full_runs_max` (2) times in the call;
- `soft deadline`: `steering.soft_min` (20) minutes in the call.

The call ends with the new error kind `stuck`. `_call` resumes the session with `steer_prompt` (why it was stopped, files changed so far, stop polling, kengash runs the suite, finish and reply), up to `steering.turns` (2) times, each with `steering.wrap_min` (10) as its soft deadline. When those run out, or the CLI has no session, the fallback chain takes over with a fresh session, as for a rate limit (escalation), and the ticket fails only when no fallback remains.

A hard timeout no longer retries the same prompt: it resumes with `timeout_prompt`, and a second timeout goes to the fallback chain.

The worktree already keeps the work between attempts, so no checkpoint commit is needed *(call)*.

### 3.2 Harness owns the slow checks (A2)
The `implement` skill: run only the test files you added or changed, in the foreground, one at a time; never poll; never run the whole suite. kengash's in-step checks and fix turns stay as they are (SP15).

### 3.3 Transient errors and honest usage (A3)
- `stream idle timeout` and `context deadline exceeded` are `network`.
- `crash` retries once after 20 s, resuming when a session exists, then goes to the fallback chain. A bad model name or a passing CLI fault no longer ends a ticket.
- A timed-out or stopped call still reports its session and tokens: the adapter's `parse` runs on the partial output, and failing that it sums the usage events. The token cap sees that spend. In 123 completed recorded calls, agy's events matched its final totals in the median call (a few fell far short); Claude's matched on input and cache, but its events hold only each message's opening output count (median 1.3% of the final), and thinking text is hidden, so a stopped Claude call's output is a floor.

### 3.4 Relay (B4)
When a ticket's worker ends, it starts what is now runnable: `relay.advance` calls the same `queue.compute` and `run_tickets` a conductor would. No LLM and no process stays behind, so rule 7 holds.

It runs only after a loop was asked for: `kengash loop claim` writes `runtime/relay.json`; `loop release` clears it, as does the relay when nothing is runnable, running or at a gate. `loop_relay: false` turns it off for a project. A plain `kengash run` starts nothing else. `kengash merge`, run by hand, and a merge from the UI advance too. Failures in the relay are logged and never fail the ticket. Decisions (gates, failed tickets) stay with the conductor and the user.

### 3.5 Path claims (B5)
`scheduler.clash` replaces `overlaps` where a claim is decided:

- paths matching `paths.shared` (default `*.g.dart`, `*.freezed.dart`, `*.generated.*`) never clash;
- a directory overlapping anything clashes, and so does an empty `touches` (the whole repo);
- exact files may overlap up to `paths.max_overlap` (default 2) *(call)*.

A real conflict surfaces at the rebase and sends the ticket back to implement, and semantic breaks are caught by the merge recheck (SP16). `paths.max_overlap: 0` restores strict behaviour. Writes inside one ticket stay single-threaded.

### 3.6 Ticket size (B6)
When a plan names more than `plan.max_files` (default 12; 0 is off) files, the planner fills `parts`: `title`, `scope`, `acceptance`, `files`, `after` (indexes of earlier parts it needs). The handoff plans the first part. kengash narrows the ticket to part 1 and adds the rest as new tickets, each depending on its `after` parts (else on the ticket's own dependencies, so disjoint parts run in parallel); dependents wait for every part.

A split that loses an acceptance line is refused and the ticket continues whole: a deterministic guard against a model dropping scope.

### 3.7 Check concurrency (B6)
`checks.parallel` (0: half the CPU cores, at least 1) limits kengash's own test runs machine-wide, using lock files.

### 3.8 Verified context (C7 and the user's request)
Rule: **what kengash can read itself it reads itself, at the moment of use.** Model recall is never passed as fact. Reviewers get no implementer narrative as fact: the coding and review agents work best with separate context (Cognition, 2026).

- **File pack.** A new `implement` session gets the current contents of the plan's files inline, each headed with its path, line count and blob id, read from the worktree when the step starts; up to `context.max_kib` (64) and the prompt limit. Omitted files are named. Paths with no file are listed as new or mistaken: a hallucinated path shows up here. Generated (`paths.shared`), binary and oversized files stay out.
- **Changed since your last turn.** A resumed session is told which files changed since it last spoke (recorded per role at each step's end). Its memory of those is out of date.
- **Memory freshness.** The digest separates choices from claims: decisions are followed, but a claim about what the code does is checked against the code, and the code wins. A line naming a path that no longer exists is tagged `[stale? path gone: …]`, not hidden. Age alone never marks a line stale.
- **Handoff is a claim.** Skills say so: where it disagrees with the code, trust the code and the Acceptance.
- **Sub-agents.** A new session is told how to delegate if its CLI offers sub-agents: state the goal, exact paths, what is verified (with `path:line`), what is not; mark recall as unverified; pass only excerpts read this session and unchanged since; delegate reading only; check what comes back. Parallel writers stay out (Cognition 2026; no sub-agent call appears in any log so far).
- **Findings are checked.** A code-review finding naming a file that does not exist, or a line past its end, is demoted to low and tagged `unverified`.

### 3.9 Review cost and precision (C8)
`review.block_on` (default `[high, medium]`): a review fails only on those severities. The default code reviewer moves to Sonnet with Opus for `critical`, through 3.10, so it stays editable; the default plan reviewer stays on Codex, a different provider *(call)*. Existing projects keep their settings: kengash never overwrites a project's SETTINGS.md.

### 3.10 Per-agent models, dynamic (user's request)
- `agents.<role>.by_importance`: importance to CLI; chain is that CLI, then `cli`, then `fallback`. A narrower scope replaces the whole mapping, so a project can clear what the defaults set.
- A model the CLI's live list lacks is skipped for the next in the chain (agy's list; Claude's aliases are not a live list, so full ids stay allowed).
- The Agents page gets a "Model by importance" row per importance, and "Other models" for the plan reviewer and the memory compactor. CLI: `kengash agent edit <role> --model-for critical=claude/opus`.

### 3.11 Skills (C9)
Exact, not longer: stop conditions, batched reads, targeted tests, evidence for findings. The 80-line and 400-word caps stay, since skill text is paid for in every new session.

## 4. New settings

```yaml
steering: {soft_min: 20, wrap_min: 10, turns: 2, poll_max: 8, full_runs_max: 2}
paths: {shared: ["*.g.dart", "*.freezed.dart", "*.generated.*"], max_overlap: 2}
context: {max_kib: 64}
checks: {turns: 2, parallel: 0}
plan.max_files: 12
review.block_on: [high, medium]
loop_relay: true
agents.<role>.by_importance: {critical: claude/opus}
```

## 5. Left out, on purpose

- `--exclude-dynamic-system-prompt-sections`: sources conflict on whether it shares cache across worktrees; test before relying on it.
- A two-pass reviewer that escalates automatically: `by_importance` covers the cost at far less machinery.
- Tree-sitter repo maps: the file pack gives exact contents for the files that matter.

## 6. Verification

`make check` stays green. New unit tests per section; the watchdog replays the recorded `ef72ed0e` event shape. `make live` and `make evals` spend the user's quota, so they run only when the user asks.

## 7. Sources

Anthropic, [multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) and [long-running harnesses](https://anthropic.com/engineering/effective-harnesses-for-long-running-agents); Cognition, [Don't Build Multi-Agents](https://cognition.ai/blog/dont-build-multi-agents) and [What's Actually Working](https://cognition.com/blog/multi-agents-working); [MAST](https://arxiv.org/abs/2503.13657); [OpenRouter doom-loop detection](https://openrouter.ai/docs/agent-sdk/call-model/doom-loop-detection); [legendary](https://pypi.org/project/legendary-mcp/) (anchored memory staleness).
