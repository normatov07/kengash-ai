# SP21: Auto mode that only asks about the loop limit

Status: approved in chat 2026-11-09 (user: "when I run with auto mode it should only ask for increase looping limit, without blocking tickets that do not depend on this ticket"). Decisions marked *(call)* are the builder's.

## 1. Why

Gates on the live store in 3 days: 16 approvals, of which 7 token caps (all approved), 6 loop caps, plus stalls, `blocked:` answers, failed tickets and merges that could not finish. The conductor stops and waits on each. While it waits, nothing else starts.

Human-in-the-loop practice: interrupt for decisions only a person can make, batch them, and keep unrelated work moving.

## 2. Goals and non-goals

In Auto mode (`loop_start: auto`), the one question is "raise this ticket's loop limit?". A gate on one ticket never holds up a ticket that does not depend on it.

Non-goals: changing behaviour outside Auto mode; removing `gate: hitl` approvals, which the user asked for on that ticket; merging against a failing check.

Anti-goal: quality paid for silence. Tests, review and the merge recheck all still run.

## 3. Design

| Gate today | In Auto mode |
|---|---|
| Token cap | Grants another `tokens.per_ticket_max` and carries on. Loops still bound the spend |
| Plan review out of rounds, or the same finding repeating (`stalled`) | Becomes the loop-limit question, routed to the failing step's `on_fail` target with its counters reset, so a raised limit replans or re-implements |
| Loop cap | Asked, as before |
| `failed` (crash, network, timeout) | The relay retries it up to 2 times, 10 minutes apart *(call)* |
| `awaiting_merge` that could not finish | The relay retries the merge, 10 minutes later *(call)* |
| `blocked:` (something only the user can supply) | Stays a gate, is not asked; listed in the conductor's final report *(call: the answer cannot be guessed)* |
| Plan approval | A plan that passes review is approved with no question |

Tickets at a gate already release their path claims and slots, and the relay starts independent work whenever a worker ends, so an unanswered question costs only that ticket and its dependents.

`kengash context` prints `loop_start: auto` so skills know the mode.

## 4. Testing
`workflow` unit tests for each route; relay tests for retries, limits and merges; a queue test that a gate leaves an independent ticket runnable.
