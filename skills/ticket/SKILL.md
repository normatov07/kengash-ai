---
name: ticket
description: Use when the user runs /kengash:ticket with an approved plan id, or with a short prompt to turn straight into tickets.
disable-model-invocation: true
metadata: {source: kengash-ai}
---
# Slice a plan into tickets

Read with your file tools; use the shell only for the `kengash` commands below, one per call. Never edit the repo's files or the `.kengash` store yourself.

0. Run `kengash --version`. If it does not print `kengash-ai <version>`, say "Install Kengash AI first: uv tool install kengash-ai" and stop.
1. A plan id: `kengash plan show <id>` must say `status: approved`. A short prompt: start a quick plan (`-p <project>` when the user named one) and use its id. On exit 4 `not a kengash project`, ask whether to register the folder; on yes, run `kengash init <folder>` and retry:

   ```
   kengash plan new --mode quick --title "<short title>" <<'EOF'
   <the user's prompt, verbatim>
   EOF
   ```

2. Cut vertical slices: each end to end, verifiable alone, small enough for one fresh context window. Split a wide refactor into expand, migrate, contract. Read `references/width.md` for edges and paths.
3. Give each slice an importance; read `references/importance.md` when assigning it.
4. Show the user a numbered list, one line per slice: `<n>. <title> · <importance> · blocked by <n…|none> · touches <paths>`. A quick plan waits for changes or a yes; an approved plan goes straight on.
5. Add the slices; `key` names a slice for `depends_on`, `touches` lists repo path prefixes, `needs` says what this slice uses from each dependency. Run it with `--check` and the same list first and change the list once as `references/width.md` says:

   ```
   kengash ticket add --plan <id> <<'EOF'
   - key: first
     title: <title>
     importance: simple
     touches: [<path>]
     depends_on: []
     needs: {}
     scope: |
       <3-8 lines: what it delivers, what it changes, what it leaves to other slices>
     acceptance: [<checkable criterion from the plan>]
   EOF
   ```

6. Run `kengash loop status -p <project>`, `<project>` being the `project:` line of `kengash plan show <id>`:
   - `loop running: …`: tell the user that loop starts these tickets; if nothing starts, run `/kengash:loop` and say to take over. Stop.
   - last line `loop_start: auto`: in the shell, not the Skill tool, run `kengash skills show loop` and follow it for `<project>`.
   - else ask "Run the loop now?": yes, as for auto; no, tell the ids and that `/kengash:loop` runs them.
