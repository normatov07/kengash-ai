---
name: loop
description: Use when the user runs /kengash:loop to have the queued tickets of their projects worked, reviewed and merged.
disable-model-invocation: true
metadata: {source: kengash-ai}
---
# Run the ticket loop

Workers do the tickets; you start them, wait, and bring the user each decision. Use the shell only for the `kengash` commands below, each as its own call, nothing chained. Never edit the repo's files or the `.kengash` store yourself.

`/kengash:loop <project>` (a name or folder) scopes the loop: add `-p <project>` to every `kengash loop claim`, `kengash next`, `kengash wait` and `kengash status` below; plain `/kengash:loop` covers every project. On exit 4 `not a kengash project`, ask whether to register that folder; only on yes, run `kengash init <folder>`, then retry.

0. Run `kengash --version`. If it does not print `kengash-ai <version>`, say "Install Kengash AI first: uv tool install kengash-ai" and stop.
1. Run `kengash doctor --quiet`. Show the user any problem it prints; warnings do not stop the loop.
2. Run `kengash loop claim`; it prints `loop claimed: <scope>`. Exit 6 prints `loop running: …`: that loop already runs these tickets; tell the user and stop. Add `--take-over` only when the user says to take over.
3. Run `kengash next`. Each line is `<id> <project> <importance> <step>→<provider> <title>`: start them all with `kengash run <id> <id>…`, then go to step 4. `nothing runnable` counting some `running`: step 4; otherwise step 6.
4. Run `kengash wait` with a 10-minute shell timeout. Exit 3: run it again. Exit 6: another session took the loop over; tell the user and stop. Each event line reads `<id> <status> loop n/max: <detail>`; `idle` means nothing is running: go to step 3.
5. Act on each event, `queued` first, then go back to step 4; read `references/events.md` when acting on an event. Merging, approving and retrying are the user's calls: ask, and wait for the answer.
6. Run `kengash loop release`. `not released`: go to step 3. `loop released`: show `kengash status` and stop. When the user says stop, run `kengash loop release --force`, then stop.
