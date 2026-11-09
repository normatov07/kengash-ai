# SP19: Landing without a human

Status: approved in chat 2026-11-09 (user: "continue, do what you needs, make it enterprise fast and quality"). Decisions marked *(call)* are the builder's.

## 1. Why

Failures and gates on the live store, 2026-11-06 to 11-09, after SP15 took `run_tests` failures from 27 to 1:

| Cost | Evidence |
|---|---|
| One merge conflict on `244385a8` | 17 hours, a rescue plan, 6 human gates, 7 tickets stuck |
| Conflict send-back cannot work | the rebase is aborted, the worktree is clean, the worker has no git write access |
| Worker told to run `gen_dart.py`, then denied | 5 `BLOCKED:` gates on `e17a7ae0` |
| Token cap at 1,000,000 | 7 of 16 approval gates, all approved, no ticket stopped by it |

`design_tokens.g.dart`, a generated file, was among the conflicted files: it needs regenerating, not merging.

## 2. Goals and non-goals

Goals: a conflict is resolved inside the ticket with no human; generated files never need a person or a model; workers may run the commands the project's own process tells them to; review sees current code.

Non-goals: optimistic parallel edits; worker git write access; pushing.

Anti-goals: conflict markers reaching main; lower quality to land faster. Tests, review and the merge recheck all still run after a resolved conflict.

## 3. Design

### 3.1 A conflict a worker can resolve
After `git rebase` conflicts and aborts, kengash replays the whole branch as one change on the base (`gitops.replay_onto`):

1. keep the branch tip at `refs/kengash/conflict/<ticket>`, dropped at merge;
2. make one squashed commit of the branch's tree on its merge base;
3. `git reset --hard <base>`, then `git cherry-pick --no-commit` that commit.

The worktree now holds every change, with conflict markers in the files that clash, and no rebase or merge in progress. Editing files is all a worker needs, and one pass settles everything *(call: a rebase would stop once per commit)*. The ticket's per-step commits become one commit on this path only.

The ticket goes back to implement with a finding naming the files. `TicketState.conflicts` holds them; kengash refuses to commit while one still has a `<<<<<<<` line, using the repair turn a failing commit hook gets.

A conflict does not cost a loop, which measures rework: up to `merge.conflict_turns` (default 2) are free, then the loop cap's rules apply.

### 3.2 Generated files
`project.generate_cmd` (e.g. `python3 tools/design/gen_dart.py`).

- A conflicted file matching a `paths.shared` file pattern takes the base's version, then the generator runs. When no other file conflicts, kengash commits and the merge goes on with no worker at all.
- Kengash's own check runs start with the generator, so generated files never go stale: `<generate_cmd> && <test_cmd>`, and a generator failure is a check failure with its own fix turns.
- A merge recheck that regenerates a file commits it before landing.

### 3.3 Commands a project allows
`project.commands`: a list of exact command prefixes workers may run, added to the test and lint commands. `generate_cmd` is always in it. The checks block of the prompt names them. Claude gets `Bash(<cmd>:*)`, Antigravity `command(<cmd>)` (those without shell operators), Codex already runs inside its workspace sandbox.

### 3.4 Review sees current code
Before a review step, a branch whose base moved is rebased when that applies cleanly. A conflict there changes nothing; the merge handles it.

### 3.5 Token cap
`tokens.per_ticket_max` default becomes 3,000,000. At 1,000,000 it stopped 7 tickets that were all approved. `kengash doctor` treats 250,000 and 1,000,000 as old defaults, as it did for 250,000. Most of the spend is the cheap implementer model; the cap still stops a runaway ticket (`244385a8` used 3.7 million).

## 4. Testing
Git tests on real repositories for replay, markers and generated files; step tests with the fake CLIs; one test that a resolved conflict lands.

## 5. Left out
Automatic re-planning of a ticket that fails repeatedly; detecting `generate_cmd` from the repo.
