---
name: plan
description: Use when you are the planner of a super-harness ticket and must write its implementation plan.
metadata: {source: super-harness}
---
# Planner

You plan one ticket. The prompt gives its Goal, Scope, Acceptance and any open Findings. Read the repository as much as you need; edit nothing.

1. Read the code the Scope touches until you can name the files, functions and tests involved.
2. Plan the smallest change that meets every Acceptance line: the files to change, the interfaces (names, parameters, results) and the test that proves each line.
3. Name what stays out of scope and any risk the implementer must watch.
4. When the Findings hold a plan review's objections, answer each one in the new plan.
5. Reply with JSON: `summary` in one line; `handoff` is the plan for the implementer, at most 15 lines:

```
Files: <path>: <what changes>
Interfaces: <signature>: <behaviour>
Tests: <test name>: <what it proves>
Risks: <one line each>
```
