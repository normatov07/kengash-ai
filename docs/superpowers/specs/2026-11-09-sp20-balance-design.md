# SP20: Parallel that holds up, and tokens spent where they pay

Status: approved in chat 2026-11-09 (user: run independent tasks in parallel without losing quality; cheap, but spend more when quality needs it). Decisions marked *(call)* are the builder's.

## 1. Why

| Measured on the live store | Number |
|---|---|
| Workers running today, until tickets were started by hand | never above 1 |
| Ready tickets left idle after the conductor's reply ended | 3, for up to 45 minutes |
| Implementer share of all tokens | 98% |
| Reviewer tokens per run (claude/opus) | about 3,000 |
| Reviews that failed | 27 of 62, every one with a high or medium finding |
| `gemini-3.8-flash-high` implementing: next review failed | 8 of 14 |
| `claude/sonnet` implementing: next review failed | 0 of 3 (small sample) |

| Research | Result | What it means here |
|---|---|---|
| The Specification Gap (2026) | Two-agent integration falls from 58% to 25% as the shared spec gets vaguer; a full spec restores the 89% single-agent ceiling; conflict reports add nothing measurable | Spend on exact interfaces between tickets, not on telling agents about conflicts |
| CooperBench (2026) | Two agents reach about half of one agent's success; expectation failures 42%, work overlap 33% | Same; path claims already handle overlap |
| Coordination modes study (2026) | Structured pipelines converge fastest with the highest quality; heavy managerial oversight degrades results | Keep fixed workflows; no manager agent, no agent chat |
| Anthropic advisor strategy | Sonnet with Opus advising: +2.7 points on SWE-bench Multilingual, 11.9% cheaper per task | Strong model for judgment, cheaper for typing. API-only, so rule 6 rules out the tool itself |
| Cascade practice | Escalation pays when the gate is deterministic, not self-reported | Escalate on a failed review or test, which kengash already knows |
| Local-Splitter (2026) | Routing and compression together save 45-79% on edit-heavy workloads | Routing first |
| Vendor MCP and LSP claims | 5-94% fewer tokens, each from the vendor's own benchmark | Not adopted, see §5 |

## 2. Goals and non-goals

Goals: ready independent tickets start by themselves whenever a loop is on; parallel tickets share exact interfaces; a failed attempt gets a stronger model; the user can see whether the balance is right.

Non-goals: a manager agent; agent-to-agent chat; API keys; a smaller reviewer model.

Anti-goal: saving tokens by weakening review. Review is under 2% of the spend and every failure it raised named a real problem.

## 3. Design

### 3.1 The relay covers every live loop
`relay.advance` acts for the scopes in `relay.json` and the scope of every live loop lease, so a loop claimed before an upgrade, or by a conductor whose reply has ended, still advances. `ticket add`, `ticket move` and `ticket set` advance too.

### 3.2 Contracts between tickets
`ticket add` takes `provides`: each interface, data format or file other tickets use, with its exact signature or shape. A ticket that another in the list depends on must have it, or `ticket add` refuses. The lines go into the ticket's Scope; a dependent's Scope gets its provider's lines beside its `needs`. The planner plans them, and the reviewer checks they exist as written.

### 3.3 A failed attempt gets a stronger model
`agents.<role>.escalate`: a list of `provider/model`. From loop 2 on, the role runs on entry `loop - 2`, the last entry for later loops, and the normal chain follows if that CLI cannot run. Loops only grow after a failed review, test or merge check, so the gate is deterministic. Off by default *(call: existing settings are never rewritten)*.

A session resumes when the provider is the same; another provider starts a new session from the Handoff and Findings.

### 3.4 `kengash stats`
From the journal, over `--days` (7): workers running when busy and minutes at each count; tickets merged and share on the first loop; tokens per merged ticket; each implementing model's runs, tokens and how often the next review passed; gates by cause. This replaces guessing about the balance.

## 4. Testing
Unit tests for each part with the fake CLIs; `ticket` skill evals on both agents; a live run of three independent tickets, measured with `kengash stats`.

## 5. Left out
- MCP or LSP tools for workers: workers run with no MCP servers, so no tool catalog in every prompt. Savings claims are the vendors' own; replicate on a real repo before adding.
- A separate consult step before a retry: the reviewer already writes the cause and a concrete fix on the strong model.
- A cheaper reviewer: see the anti-goal.
