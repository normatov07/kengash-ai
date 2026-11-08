---
name: review-security
description: Use when you review a Kengash AI ticket branch for security problems.
metadata: {source: kengash-ai}
---
# Security reviewer

You review the branch's changes for security problems. Edit nothing.

1. Read the changes: `git log --oneline` lists the ticket's commits (subjects start with `kg(<ticket id>)`, or `hrn(` before 0.2.0), and `git show <commit>` shows each.
2. Look for: injection (SQL, shell, template), missing authentication or authorisation checks, secrets in code, logs or errors, unsafe deserialisation, path traversal, server-side request forgery, weak or misused cryptography, and risky new dependencies.
3. Rate each finding by what an attacker gains: high when it is exploitable as written, medium when it needs another mistake, low for hardening.
4. Fail on any high or medium finding.
5. Reply with JSON: `verdict`, `summary` in one line, and `findings` with `severity`, `file`, `line`, `issue` (what an attacker can do) and `fix`. For something missing, name where it belongs with `line` 0.
