# SP16: Shared memory and parallel tickets (design)

Date: 2026-11-07. Status: approved for build. Source: the user's report on chess-samurai: memory and decisions are "almost not used"; key design choices should be recorded on their own; tickets "run one by one", and independent ones should run at once, fast without losing cost or quality. The user chose auto-merge as the default for new projects and their own (merges are rechecked first, see §3.9), and a dry check plus a short live run before releasing 0.6.0. Calls marked *call* are the builder's.

## 1. Why

**Memory.** The store after 2 plans and 25 chess-samurai tickets: global MEMORY.md and DECISIONS.md hold 0 lines. Causes:

1. **Workers never read memory.** System spec §4.5 says workers get a MEMORY digest and read PROCESS.md; neither was built. Worker prompts carry Goal, Scope, Acceptance, Handoff and Findings only, and a ticket worktree has no `.kengash` link. The chess-samurai PROCESS.md design rules reached no worker.
2. **Recording depends on a skill firing.** `kengash:memory` triggers on phrases ("always", "we decided"). An agent running `/kengash:grill` or `/kengash:loop` follows that skill and does not switch to another.
3. **The user's design answers stay inside plans.** Grill writes `question → answer` lines into the plan's `## Decisions`; nothing records any of them in DECISIONS.md.
4. **Workers cannot propose decisions.** A work reply is `summary` and `handoff`; choices made inside a ticket are lost.

**Parallelism.** The journal shows 1,540 minutes with one chess-samurai step running and 533 minutes with two or more (74% serial). Causes:

1. **Path claims are coarse.** 13 of 22 tickets claim `test/`; others claim `pubspec.yaml` or `lib/presentation/`. Prefixes overlap, so most pairs clash. At 05:16 four tickets were ready and two ran (d1db976f held by `test/`, d24db74a by `pubspec.yaml`).
2. **Every in_process ticket holds its paths**, including those at a gate. 1d0123a6 sat at `needs_approval` for hours holding `lib/presentation/`.
3. **Planning holds paths too**, though plan and review_plan edit nothing (about 40% of a ticket's time).
4. **The user's merge is on the critical path.** Tickets waited about 100 minutes at `awaiting_merge`; dependents start only on `done/merged`.
5. **Slicing gives no rule for `depends_on` or narrow `touches`**, so the graph was eight levels deep.
6. **A merge is not rechecked.** It rebases onto a base that may have moved, then fast-forwards with no test run. More parallel work would land untested combinations on main.

## 2. Goals and non-goals

- Every new worker session sees the user's preferences, the project's decisions and its process notes, capped in size.
- Lasting design choices reach DECISIONS.md without anyone remembering to run a command: from approved plans, and from merged tickets.
- Independent tickets plan at once; tickets only wait for each other when they would edit the same files.
- Main stays green under parallel merges: every merge onto a moved base is tested first.
- Anti-goals: no parallel writers in one ticket (single writer per worktree, Cognition 2026); no memory written by a worker that bypasses review (proposals land only when the ticket merges); no extra model call per memory write; no daemon.

## 3. Decisions

### Memory read

1. **Memory digest in every new session.** `memory.digest(paths, slug) -> str` builds a `## Memory` block: the project's PROCESS.md from its first `## ` heading (at most 3,000 characters), the DECISIONS.md lines tagged `[<slug>]` or `[global]`, newest kept first (at most 2,500), and MEMORY.md's lines under their section names (at most 1,500). Over a cap, the oldest lines go and one line `… N older lines in <file>` stays. Empty parts drop out, and an empty digest drops the block. The digest is redacted. The block's lead: "The user's preferences and this project's settled decisions and process. Follow them; newer lines override older ones. When the Scope conflicts with one, follow the Scope and say so in your handoff." It comes first in `new_prompt`, before Goal. Resumed sessions already hold it and do not get it again. The plan reviewer gets the same digest in place of its decisions block.

### Memory write

2. **Plans record their lasting decisions on approval.** PLAN_SECTIONS gains `Lasting decisions` after `Decisions`. Each `- ` line reads `<decision>. why: <reason>. rejected: <alternative>.` (`why` and `rejected` are optional). `kengash plan approve` records each line in DECISIONS.md tagged with the plan's project. A missing `why` becomes `plan <id>`. Approval then prints `DECISIONS.md +N lines`. The grill and plan skills write the section with criteria (§3.5).
3. **Workers propose decisions; merges record them.** Work replies gain `decisions: [{decision, why, rejected}]`; the strict schema requires the field, and an empty list is valid. Kengash keeps at most 3 per reply and 6 per ticket, deduplicated, in a new ticket section `## Decisions` (after Findings). Each line reads `- <decision>. why: <why>. rejected: <rejected>.`. Review prompts show the section, and the review-code skill makes a line that is not a lasting choice, or that contradicts Memory, a finding. On a successful merge, kengash records each line in DECISIONS.md tagged with the project. A parked or closed ticket's proposals are never recorded (an ADR lands with its code).
4. **Process notes through kengash.** `kengash memory add "<line>" --process` appends `- <line>` under `## Process notes` in the project's PROCESS.md, journaled and committed like other memory writes. At the 100-line cap it refuses with `PROCESS.md is at its 100-line cap; edit it in the UI or by hand`. `--process` cannot be combined with `--decision`, `--section` or `--rejected`.
5. **When to record (criteria, used by skills and `kengash context`).** DECISIONS.md takes a settled choice that later work must follow and the code does not make obvious:
   - architecture and module boundaries;
   - public interfaces, data formats and schemas;
   - chosen libraries, engines and tools;
   - design-system values and rules (palette, type, spacing, motion timings);
   - platform, performance and security targets;
   - the source of truth for something;
   - naming conventions.
   MEMORY.md takes how the user works, across projects:
   - Preferences: "always", "never", "prefer", "from now on";
   - Working style;
   - Goals;
   - Turned down: approaches rejected for good.
   PROCESS.md takes how this project builds, tests, ships, and where its truth lives. Never record:
   - one ticket's details;
   - what the code, README or plan already says;
   - guesses or open questions;
   - secrets.
   `kengash context` ends with a short `Record:` paragraph stating this. The memory skill carries it. Grill, plan and loop each get one rule pointing to it.
6. **Near-duplicates are already recorded.** `memory.add` compares lines after lowercasing, collapsing whitespace and dropping trailing punctuation. For decisions it also ignores the date and tag. A match prints `already recorded`. No model call is made.

### Parallel tickets

7. **Only the editing phase holds paths.** A workflow's *editing phase* is its first `edit`-kind step and every step after it (`workflow.edit_phase(settings, name, step, hitl) -> bool`). A ticket *holds* its `touches` when it is in_process and either (a) its step is in the editing phase and its sub-status is not `needs_approval`, `stalled`, `failed`, `paused` or `waiting_paths`, or (b) it is `awaiting_merge`. Its finished edits wait to land, so a new writer on those files would conflict for sure. Planning steps neither hold nor check paths, so the scheduler, `kengash next` and `kengash run` start a ticket whose first step is planning regardless of overlap. A ticket whose start step is in the editing phase is checked against holders only.
8. **Waiting for paths inside the job.** When a running job reaches an editing-phase step and another ticket holds an overlapping path, the ticket moves to `in_process/waiting_paths`. The job journals `ticket.moved` with reason `touches overlap <id>` and polls every 5 s (`PATH_POLL_S`), beating and honouring park and pause, until the paths are free. The check and the move to the step status happen together under the project lock, so two waiters never both take the same paths. Holders never wait on waiters, so the wait cannot deadlock. *call:* waiting happens in the job, like `waiting_slot`, rather than re-queueing, so the plan session and slot logic stay as they are.
9. **Merge queue: recheck on a moved base.** Merges of one project serialize on `merge-<slug>.lock`, held for the whole merge. After the rebase, when the rebase moved HEAD, the project has a test or lint command, and the workflow has an enabled `check` step, kengash runs the checks in the worktree before fast-forwarding. The project lock is not held while they run. A failure sends the ticket back to implement exactly like a rebase conflict (loop + 1, or `needs_approval` at the cap): the digest finding goes to Findings, the output to `## Check output`, and `checks.end` is journaled with step `merge`. When main moved by hand in the meantime, the fast-forward fails and the merge reports `<base> moved; run kengash merge <id> again`. A rebase that moved nothing runs no checks.
10. **Auto-merge by default.** `merge.mode` defaults to `auto` in the model and the shipped SETTINGS.md. `hitl` tickets still wait for the user. Under `auto`, a merge skipped because the main working tree is dirty or off the base branch journals `ticket.awaiting_merge` with reason `main working tree has changes; merge waits for you` (or `… is on <branch>`). The user's store defaults and both projects are switched with `kengash settings set` during validation, as the user chose.
11. **Fresh base before the first edit.** When a ticket enters an editing-phase step, its branch has no commits beyond the base, and its worktree is clean, the worktree fast-forwards to the base tip (`gitops.catch_up(worktree, base) -> bool`). Implementation then starts from the newest main, including tickets merged while it planned.
12. **The planner names its files; touches narrow.** Read-kind steps before the editing phase reply with output kind `plan`: `{summary, handoff, files, decisions}`. `files` holds the repo-relative paths the plan changes or creates. When such a step passes with 1 to 40 valid paths (relative, no `..`, normalized, deduplicated), the ticket's `touches` become exactly those paths. The Log notes `touches narrowed to N files`. Otherwise touches stay as sliced. The plan role skill says so.
13. **Critical path first.** Inside a project, ready candidates sort by the length of their longest chain of not-done dependents (descending), then importance, then age. Projects still take turns. *call:* longest chain over dependent count; it minimises makespan for unit-cost chains (Hu's rule).
14. **Slicing for width.** The ticket skill adds two rules:
   - `depends_on` names only slices whose code this slice calls, extends or edits after it exists. Slices that share an area run in parallel, and kengash keeps their edits apart.
   - `touches` names the narrowest folders or files, never a top-level folder unless the slice rewrites most of it, and puts tests under the code's own test path.

## 4. Contract changes (same commits as the code)

- System spec §4.5: workers get the memory digest (decision 1). It records who writes plan decisions and merged ticket decisions, and adds `--process`.
- System spec §5: the `plan` output kind, `decisions`, and the ticket `## Decisions` section.
- System spec §7: claims and phases, `waiting_paths` and the scheduling order. The same changes go into SP3 spec §7.
- System spec §9: the merge queue lock and the recheck. The `merge.mode` default becomes `auto`.
- `docs/conventions/memory-files.md`: the §3.5 criteria, `Lasting decisions` and the ticket `## Decisions` section.

## 5. Left out, on purpose

- **Stacked branches** (a dependent starting from an unmerged dependency's branch): auto-merge plus the recheck unblocks dependents within a minute, at far less complexity.
- **Model-based memory reconciliation** (Mem0-style UPDATE/DELETE): it adds a call per write. Newest-wins in the digest, plus compaction, cover it.
- **Supersede markers in DECISIONS.md**: the digest tells agents newer lines win.
- **Conflict prediction from diffs at run time**: the narrowed files plus the merge recheck are enough.

## 6. Milestones and exit criteria

- `make check` is green, and every decision above has a test that failed first.
- A dry run on the real chess-samurai store shows which ready tickets start together under the new rules, compared with the old ones.
- A live loop over 2 or more chess-samurai tickets shows overlapping planning, the `## Memory` block in a worker prompt, and an auto-merge with or without a recheck.
- Release 0.6.0 is prepared: version, plugin manifests, CHANGELOG (SP15 and SP16) and README upgrade notes. The user pushes the tag.
