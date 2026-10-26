---
name: to-loop
description: Use when the user runs /to-loop to have the queued tickets of their projects worked, reviewed and merged.
disable-model-invocation: true
metadata: {source: kengash-ai}
---
# Run the ticket loop

Workers do the tickets; you start them, wait, and bring the user each decision. Use the shell only for the `harness` commands below, each as its own call with nothing chained before or after it. Never edit the repo's files or the `.harness` store yourself.

0. Run `harness --version`. If it does not print `kengash-ai <version>`, say "Install Kengash AI first: uv tool install git+https://github.com/normatov07/kengash-ai" and stop.
1. Run `harness doctor --quiet`. Show the user any problem it prints; warnings do not stop the loop.
2. Run `harness next`. Each line is `<id> <project> <importance> <step>→<provider> <title>`; `nothing runnable` ends the loop: show `harness status` and stop.
3. Start every listed ticket: `harness run <id> <id>…`. Each prints `started` or `skipped <id>: <reason>`.
4. Run `harness wait` with a 10-minute shell timeout. Exit 3 means nothing happened yet: run it again. Each event line reads `<id> <status> loop n/max: <detail>`; `idle` means nothing is running: go to step 2.
5. Act on each event, then go back to step 4:

   | Status | What you do |
   |---|---|
   | `awaiting_merge` | ask the user; on yes, `harness merge <id>` |
   | `needs_approval` | explain the detail (loop or token cap, approval step); on yes, `harness approve <id>` (`--loops N` for more loops) |
   | `stalled` | show `harness ticket show <id>` findings; offer to re-plan with `/to-plan` or to retry with `harness run <id>` |
   | `failed` | show the reason; once it is fixed (for example a sign-in), `harness run <id>` |
   | `done/…` or `merged` | tell the user |

   Merging, approving and retrying are the user's calls: ask, and wait for the answer.
6. Stop when the user says so, or when step 2 finds nothing runnable and nothing is running.
