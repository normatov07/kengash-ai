---
name: to-loop
description: Use when the user runs /to-loop to have the queued tickets of their projects worked, reviewed and merged.
disable-model-invocation: true
metadata: {source: kengash-ai}
---
# Run the ticket loop

Workers do the tickets; you start them, wait, and bring the user each decision. Use the shell only for the `kengash` commands below, each as its own call with nothing chained before or after it. Never edit the repo's files or the `.kengash` store yourself.

0. Run `kengash --version`. If it does not print `kengash-ai <version>`, say "Install Kengash AI first: uv tool install kengash-ai" and stop.
1. Run `kengash doctor --quiet`. Show the user any problem it prints; warnings do not stop the loop.
2. Run `kengash next`. Each line is `<id> <project> <importance> <step>→<provider> <title>`; `nothing runnable` ends the loop: show `kengash status` and stop.
3. Start every listed ticket: `kengash run <id> <id>…`. Each prints `started` or `skipped <id>: <reason>`.
4. Run `kengash wait` with a 10-minute shell timeout. Exit 3 means nothing happened yet: run it again. Each event line reads `<id> <status> loop n/max: <detail>`; `idle` means nothing is running: go to step 2.
5. Act on each event, then go back to step 4:

   | Status | What you do |
   |---|---|
   | `awaiting_merge` | ask the user; on yes, `kengash merge <id>` |
   | `needs_approval` | explain the detail (loop or token cap, approval step); on yes, `kengash approve <id>` (`--loops N` for more loops) |
   | `stalled` | show `kengash ticket show <id>` findings; offer to re-plan with `/to-plan` or to retry with `kengash run <id>` |
   | `failed` | show the reason; once it is fixed (for example a sign-in), `kengash run <id>` |
   | `done/…` or `merged` | tell the user |

   Merging, approving and retrying are the user's calls: ask, and wait for the answer.
6. Stop when the user says so, or when step 2 finds nothing runnable and nothing is running.
