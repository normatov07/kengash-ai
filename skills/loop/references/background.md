# Watching workers from the background

Read this when your shell can run a command in the background and tell you when it ends (Claude Code can). The session then never freezes on a blocking call.

- Each `started` line ends with `(watch: …)`. A tab there (`orca tab kg <id>`, `tmux tab kg <id>`, `gnome-terminal tab kg <id>`) already shows that worker live: start nothing for it. When it names a command instead, no terminal was found: start that `kengash logs <id> -f` in the background once, so the user opens it like a subagent. It ends by itself when the ticket stops. Do not read its output into the conversation.
- Start `kengash wait` in the background too, instead of blocking on it, and keep answering the user meanwhile. When the host says it ended, read its output and go on as the loop says: event lines go to step 5, `idle` to step 3, and exit 3 means start it again.
