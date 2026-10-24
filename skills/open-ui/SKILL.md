---
name: open-ui
description: Use when the user runs /open-ui to see their projects, tickets, workflows, agents and memory in the local harness web UI.
disable-model-invocation: true
metadata: {source: super-harness}
---
# Open the harness UI

The UI is a local web app that `harness` starts and reuses. Use the shell only for the commands below, each as its own call with nothing chained. Never edit the repo's files or the `.harness` store yourself.

0. Run `harness --version`. If it does not print `super-harness <version>`, say "Install super-harness first: uv tool install git+https://github.com/normatov07/super-harness" and stop.
1. Run `harness ui open`. It starts the UI, or reuses the one already running, opens the browser, and prints the link:

   ```
   http://127.0.0.1:<port>/?token=<token>
   ```

2. If it exits 4 and prints `install the UI: …`, the UI extra is missing. Show the user that line and ask whether to install it. Only on yes, run

   ```
   uv tool install --force 'super-harness[ui] @ git+https://github.com/normatov07/super-harness'
   ```

   then run `harness ui open` again. On no, stop.
3. Any other error: show the user what it printed and stop.
4. Give the user the link in one line, and say `harness ui stop` ends the UI.
