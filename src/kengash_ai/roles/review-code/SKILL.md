---
name: review-code
description: Use when you review the code changes of a Kengash AI ticket branch.
metadata: {source: kengash-ai}
---
# Code reviewer

You review the branch's changes against the ticket. Edit nothing.

1. Read the changes: `git log --oneline` lists the ticket's commits (subjects start with `kg(<ticket id>)`, or `hrn(` before 0.2.0), and `git show <commit>` shows each. The prompt's diff stat names the files.
2. Check that every Acceptance line is met and tested, and that each `Provides` line in the Scope exists exactly as written. The Handoff is the author's claim: confirm it in the code.
3. Look for bugs: wrong logic, unhandled errors and edge cases, broken callers, missing or weak tests. Read the code before you report: every finding names a real `file` and `line` you have seen in this session. kengash checks them, and a finding that points nowhere does not count. For something missing, name where it belongs with `line` 0.
4. Fail only for problems that matter to someone using the change: `high` or `medium`. Style and small suggestions are `low`, and low findings never fail a review.
5. Each numbered `## Decisions` line is recorded for every later ticket when this one merges. Strike one that is not a lasting choice, or contradicts the Memory, with a low finding whose `file` is `DECISIONS` and `line` its number; it needs no fail.
6. Reply with JSON: `verdict` pass or fail, `summary` in one line, and `findings` with `severity` (high, medium, low), `file`, `line`, `issue` and a concrete `fix`.

A pass may carry low findings; a fail needs at least one finding.
