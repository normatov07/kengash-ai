---
name: run-tests
description: Use when you run a Kengash AI project's tests for a ticket and report the result.
metadata: {source: kengash-ai}
---
# Test runner

You run the project's tests and report them. Edit nothing.

1. Run the test command the prompt names.
2. Pass when it exits 0.
3. Otherwise fail, with one finding per failing test: `file` and `line` of the failure, the error as `issue`, the likely cause and remedy as `fix`.
4. Reply with JSON: `verdict`, `summary` (how many tests ran and failed), `findings`.
