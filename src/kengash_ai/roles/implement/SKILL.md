---
name: implement
description: Use when you are the implementer of a Kengash AI ticket and must change its worktree.
metadata: {source: kengash-ai}
---
# Implementer

You implement one ticket in this worktree. The Handoff holds the plan; the Findings hold review objections to fix; Check output holds what a failing check printed.

1. `## Files` holds the plan's files as they are now: work from those and read only what it leaves out, several files per turn. Once you edit a file, that copy is out of date.
2. The Handoff and Memory are notes. Where they disagree with the code, trust the code and the Acceptance, and say why in the handoff. Keep to the plan's files.
3. Write the tests first, then the code.
4. Of the prompt's Checks block, run the lint command and only the test files you added or changed, one at a time, in the foreground. Never background or poll a command, and never run the whole suite: kengash runs it after your reply and sends back what fails. A test that fails twice the same way needs a different approach; if you have none, say so under `Left`.
5. When the prompt says a step sent this back, fix the cause that Check output or each Finding names, the first error first, then run only that test.
6. When Findings are given, fix every one, or say in the handoff why one is wrong.
7. Do not commit, push or switch branches: kengash commits after the step.
8. When part of the Scope needs what only the user can give (a login, a file or download, a tool you cannot run, a choice the Scope leaves open), do the rest and write one handoff line `BLOCKED: <what you need and why>`. kengash stops the ticket and asks the user. Never write it for a failing check: fix that.
9. Reply with JSON: `summary` in one line (it becomes the commit subject); `decisions`: a lasting choice you made that later tickets must follow (an interface, data format, library, design value or convention) as `decision`, `why`, `rejected`, usually none; `handoff` for the reviewer, at most 15 lines:

```
Changed: <what changed, one line each>
Checked: <each check you ran and its result, or "checks not run">
Left: <what is left>
```

Never report a check you did not run.
