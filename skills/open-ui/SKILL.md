---
name: open-ui
description: Use when the user runs /open-ui to see their projects, tickets, workflows, agents and memory in the local kengash web UI.
disable-model-invocation: true
metadata: {source: kengash-ai}
---
# Open the kengash UI

The UI is a local web app that `kengash` starts and reuses. Use the shell only for the commands below, each as its own call with nothing chained. Never edit the repo's files or the `.kengash` store yourself.

0. Run `kengash --version`. If it does not print `kengash-ai <version>`, say "Install Kengash AI first: uv tool install kengash-ai" and stop.
1. Run `kengash ui open`. It starts the UI, or reuses the one already running, opens the browser, and prints the link:

   ```
   http://127.0.0.1:<port>/?token=<token>
   ```

2. If it exits 4 and prints `install the UI: …`, the UI extra is missing. Show the user that line and ask whether to install it. Only on yes, run

   ```
   uv tool install --force 'kengash-ai[ui]'
   ```

   then run `kengash ui open` again. On no, stop.
3. Any other error: show the user what it printed and stop.
4. Give the user the link in one line, and say `kengash ui stop` ends the UI.
