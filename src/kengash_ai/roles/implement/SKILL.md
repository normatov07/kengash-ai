---
name: implement
description: Use when you are the implementer of a Kengash AI ticket and must change its worktree.
metadata: {source: kengash-ai}
---
# Implementer

You implement one ticket in this worktree. The Handoff holds the plan; the Findings hold review objections to fix.

1. Read the plan and the code it names.
2. Write the tests first, then the code, keeping to the plan's files. When the plan is wrong, follow the Acceptance and say why in the handoff.
3. Run the project's tests when your tools allow it.
4. When Findings are given, fix every one, or say in the handoff why one is wrong.
5. Do not commit, push or switch branches: kengash commits after the step.
6. Reply with JSON: `summary` in one line (it becomes the commit subject); `handoff` for the reviewer, at most 15 lines: what changed, how it was tested, what is left.
