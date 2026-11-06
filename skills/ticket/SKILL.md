---
name: ticket
description: Use when the user runs /kengash:ticket with an approved plan id, or with a short prompt to turn straight into tickets.
disable-model-invocation: true
metadata: {source: kengash-ai}
---
# Slice a plan into tickets

Read with your file tools; use the shell only for the `kengash` commands below, each as its own call, nothing chained. Never edit the repo's files or the `.kengash` store yourself.

0. Run `kengash --version`. If it does not print `kengash-ai <version>`, say "Install Kengash AI first: uv tool install kengash-ai" and stop.
1. A plan id: `kengash plan show <id>` prints it; it must say `status: approved`. A short prompt instead: start a quick plan (add `-p <project>` when the user named a project or folder after it) and use its id. On exit 4 `not a kengash project`, ask whether to register that folder; only on yes, run `kengash init <folder>`, then retry:

   ```
   kengash plan new --mode quick --title "<short title>" <<'EOF'
   <the user's prompt, verbatim>
   EOF
   ```

2. Cut vertical slices: each end to end, verifiable alone, small enough for one fresh context window. Split a wide refactor into expand, migrate, contract.
3. Give each slice an importance; read `references/importance.md` when assigning it.
4. Show the user a numbered list, one line per slice: `<n>. <title> · <importance> · blocked by <n…|none> · touches <paths>`. A quick plan waits for changes or a yes; an approved plan goes straight on.
5. Add the slices; `key` names a slice so others can depend on it, and `touches` lists repo path prefixes:

   ```
   kengash ticket add --plan <id> <<'EOF'
   - key: first
     title: <title>
     importance: simple
     touches: [<path>]
     depends_on: []
     scope: |
       <3-8 lines: what it delivers end to end; files, modules and interfaces it changes; plan sections it implements; what it leaves to other slices>
     acceptance: [<checkable criterion from the plan>]
   EOF
   ```

   It prints `N tickets: <ids> (R ready, B blocked)`.
6. Run `kengash loop status -p <project>`, `<project>` being the `project:` line of `kengash plan show <id>`:
   - `loop running: …`: tell the user that loop starts these tickets once any open question there is answered; if nothing starts, `/kengash:loop` takes over. Stop.
   - last line `loop_start: auto`: run `kengash skills show loop` and follow it for `<project>`.
   - else ask "Run the loop now?": yes, as for auto; no, tell the ids and that `/kengash:loop` runs them.
