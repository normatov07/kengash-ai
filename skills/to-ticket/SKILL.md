---
name: to-ticket
description: Use when the user runs /to-ticket with an approved plan id, or with a short prompt to turn straight into tickets.
disable-model-invocation: true
metadata: {source: super-harness}
---
# Slice a plan into tickets

Read with your file tools; use the shell only for the `harness` commands below, each as its own call with nothing chained before or after it. Never edit the repo's files or the `.harness` store yourself.

0. Run `harness --version`. If it does not print `super-harness <version>`, say "Install super-harness first: uv tool install git+https://github.com/normatov07/super-harness" and stop.
1. A plan id: `harness plan show <id>` prints it; it must say `status: approved`. A short prompt instead: start a quick plan, then use its id:

   ```
   harness plan new --mode quick --title "<short title>" <<'EOF'
   <the user's prompt, verbatim>
   EOF
   ```

2. Cut vertical slices: each one end to end, verifiable on its own, small enough for one fresh context window. Split a wide refactor into expand, migrate, contract.
3. Give each slice an importance; read `references/importance.md` when assigning importance.
4. Show the user a numbered list, one line per slice: `<n>. <title> · <importance> · blocked by <n…|none> · touches <paths>`. Wait for changes or a yes.
5. Add the agreed slices; `key` names a slice so others can depend on it, and `touches` lists repo path prefixes:

   ```
   harness ticket add --plan <id> <<'EOF'
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
6. Tell the user the ticket ids and that `/to-loop` runs them.
