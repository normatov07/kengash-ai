---
name: ticket
description: Use when the user runs /kengash:ticket with an approved plan id, or with a short prompt to turn straight into tickets.
disable-model-invocation: true
metadata: {source: kengash-ai}
---
# Slice a plan into tickets

Read with your file tools; use the shell only for the `kengash` commands below, each as its own call with nothing chained before or after it. Never edit the repo's files or the `.kengash` store yourself.

0. Run `kengash --version`. If it does not print `kengash-ai <version>`, say "Install Kengash AI first: uv tool install kengash-ai" and stop.
1. A plan id: `kengash plan show <id>` prints it; it must say `status: approved`. A short prompt instead: start a quick plan, adding `-p <project>` when the user named a project or its folder after the prompt, then use its id. On exit 4 `not a kengash project`, ask whether to register that folder; only on yes, run `kengash init <folder>`, then retry:

   ```
   kengash plan new --mode quick --title "<short title>" <<'EOF'
   <the user's prompt, verbatim>
   EOF
   ```

2. Cut vertical slices: each one end to end, verifiable on its own, small enough for one fresh context window. Split a wide refactor into expand, migrate, contract.
3. Give each slice an importance; read `references/importance.md` when assigning importance.
4. Show the user a numbered list, one line per slice: `<n>. <title> · <importance> · blocked by <n…|none> · touches <paths>`. Wait for changes or a yes.
5. Add the agreed slices; `key` names a slice so others can depend on it, and `touches` lists repo path prefixes:

   ```
   kengash ticket add --plan <id> <<'EOF'
   - key: first
     title: <title>
     importance: simple
     touches: [<path>]
     depends_on: []
     scope: <what this slice delivers, end to end>
     acceptance: [<checkable criterion>]
   EOF
   ```

   It prints `N tickets: <ids> (R ready, B blocked)`.
6. Tell the user the ticket ids and that `/kengash:loop` runs them.
