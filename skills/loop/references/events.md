# Acting on a wait event

| Status | What you do |
|---|---|
| `queued: N tickets ready` | run `kengash next`, then `kengash run` the ids it lists |
| `awaiting_merge` | ask the user; on yes, `kengash merge <id>` |
| `needs_approval` | explain the detail (loop or token cap, approval step, or `blocked: <what>`: quote it and ask what the user supplies or decides); on yes, `kengash approve <id>` (`--loops N` for more loops; for a blocked ticket `--note "<the user's answer>"`); an answer that sets a rule for later work is also recorded with `kengash memory add`, as the `# Record` part of `kengash context` says |
| `stalled` | show `kengash ticket show <id>` findings; offer to re-plan with `/kengash:plan` or to retry with `kengash run <id>` |
| `failed` | show the reason; once it is fixed (for example a sign-in), `kengash run <id>` |
| `done/…` or `merged` | tell the user |
