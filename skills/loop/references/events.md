# Acting on a wait event

## Auto mode

When `kengash loop status` prints `loop_start: auto`, the one thing you ask is whether to raise a loop limit (`needs_approval` with a `loop cap` detail). Put every such ticket in one question, recommend a number, and on yes run `kengash approve <id> --loops N`. Other tickets keep running while the user decides, so never hold them back for it.

Ask nothing else. kengash grants tokens, retries failed tickets and retries merges itself. Do not act on `failed`, `stalled` or `awaiting_merge`. A `blocked:` ticket waits for something only the user can supply: leave it, and list it in your final report with what it needs. A ticket with `gate: hitl` is still the user's to approve.

## Otherwise

| Status | What you do |
|---|---|
| `queued: N tickets ready` | run `kengash next`, then `kengash run` the ids it lists |
| `awaiting_merge` | the detail says why it waits (under `merge.mode: auto`, why kengash could not merge it, such as uncommitted changes in the main working tree); ask the user; on yes, `kengash merge <id>` |
| `needs_approval` | explain the detail (loop or token cap, approval step, or `blocked: <what>`: quote it and ask what the user supplies or decides); on yes, `kengash approve <id>` (`--loops N` for more loops; for a blocked ticket `--note "<the user's answer>"`); an answer that sets a rule for later work is also recorded with `kengash memory add`, as the `# Record` part of `kengash context` says |
| `stalled` | show `kengash ticket show <id>` findings; offer to re-plan with `/kengash:plan` or to retry with `kengash run <id>` |
| `failed` | show the reason; once it is fixed (for example a sign-in), `kengash run <id>` |
| `done/…` or `merged` | tell the user |
