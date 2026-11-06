# Watching workers from the background

Read this when your shell can run a command in the background and tell you when it ends (Claude Code can). The user then watches each worker like a subagent, and the session never freezes on a blocking call.

- After `kengash run`, start `kengash logs <id> -f` in the background once per started ticket. Your host lists it as a running task, and the user opens it to watch that worker live: each file it reads or edits, each command, its replies. It ends by itself when the ticket stops. Do not read its output into the conversation.
- Start `kengash wait` in the background too, instead of blocking on it, and keep answering the user meanwhile. When the host says it ended, read its output and go on as the loop says: event lines go to step 5, `idle` to step 3, and exit 3 means show its progress lines and start it again.
