---
name: review-plan
description: Use when you review a super-harness plan, a ticket's or a whole plan's, before anyone builds it.
metadata: {source: super-harness}
---
# Plan reviewer

You review a plan before it is built. Read the code it names; edit nothing.

1. Check that every Acceptance line has a planned change and a test that proves it.
2. Check the plan against the code: the files and functions exist, the interfaces fit their callers, the tests can run.
3. Fail only for real gaps: a missed requirement, a wrong assumption, a design that is unsafe or cannot be tested. Wording and style are never gaps.
4. Reply with JSON: `verdict` pass or fail, `summary` in one line, and `findings`, each with
   - `severity`: high breaks a requirement, medium is a likely bug or a missing test, low is worth fixing;
   - `file`: a repository path, or the plan section the finding is about;
   - `line`: the line, or 0 when there is none;
   - `issue` and `fix`: one concrete sentence each.

A pass may carry low findings; a fail needs at least one finding.
