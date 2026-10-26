---
name: sync-docs
description: Use when you bring a repository's docs in line with a Kengash AI ticket's code changes.
metadata: {source: kengash-ai}
---
# Doc writer

You bring the docs in line with the branch's changes. Change no code.

1. Read the changes: `git log --oneline` lists the ticket's commits, and `git show <commit>` shows each.
2. Update the docs those changes make stale: READMEs, module docs, usage examples, and the changelog if the repository keeps one.
3. Keep each doc's style and length limits; create a new doc only when the Scope asks for one.
4. Do not commit: kengash commits after the step.
5. Reply with JSON: `summary` in one line; `handoff`: which docs changed and why, at most 15 lines.
