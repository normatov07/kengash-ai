# SP13: Watch, strong monitoring of every worker (design)

Date: 2026-11-07. Status: designed by the builder at the user's request ("make the design yourself… we should watch agents work, we need strong monitoring, that itself is enough… optimal token usage and cheap work"); the user chose two things in the conversation: viewer tabs open automatically, and they work in Orca, tmux or the plain Ubuntu terminal. Calls marked *call* are the builder's and open to veto.

## 1. Why

Kengash lets one developer run many projects at once on the coding-agent subscriptions they already pay for. The conductor (Claude Code, Codex or agy) plans and steers; detached workers on any of those CLIs do the steps, several in parallel. So the user's question is always the same: *what is each worker doing right now, and does anything need me?*

SP12 made that answerable (`kengash ps`, `kengash logs <id> -f`, `wait` progress, the UI's Live tab), but only on request: the user has to know an id and type a command, or open the UI. The user, on 2026-11-07: workers should be visible like subagents, each in its own terminal tab, opened automatically; monitoring must be strong and cheap.

## 2. What the purpose decides

1. **Monitoring costs no model tokens.** Everything shown is parsed from the stream logs and the journal by `kengash` itself (`ops.activity`, `ops.progress`). No watcher agent, no summaries by a model (*call*: a watcher agent per worker would spend tokens re-reading what a parser reads for free).
2. **The conductor's context stays small.** Workers' transcripts go to the user's screen, never into the conductor's context. The loop skill stops relaying progress the user can already see.
3. **No daemon** (hard rule 7). Tabs and dashboards are ordinary foreground commands the user can close; whatever starts a worker opens its tab.
4. **Any terminal, no hard dependency.** Orca, tmux and gnome-terminal are detected; any other terminal is one setting; with none, kengash prints the command to run.
5. **Push only what needs the user.** A desktop notification when a ticket stops at a gate; everything else is pull (tabs, dashboard, UI).
6. **Agents do not chat with each other** (*call*). The board, meaning the plan, the ticket's Handoff and Findings and MEMORY.md, already carries what each agent needs. Free conversation would double the tokens of two sessions per message and loop without a referee. The user can talk to any worker directly (§3.6).

## 3. Decisions

### 3.1 Viewer tabs, opened automatically

- Whenever kengash starts a ticket's worker (`run`, an approval that restarts it, `resume`), it opens a **worker tab** titled `kg <id>` running `kengash logs <id> --watch`.
- Whenever `kengash loop claim` takes a new lease, it opens one **dashboard tab** titled `kg watch` (or `kg watch <project>`) running `kengash watch [-p <project>]`.
- At most one tab per key: a viewer registers itself in `runtime/viewers/<key>.json` (`ticket-<id>`, `watch-<scope>`) with its pid. An opener skips a key whose viewer runs, and holds a 15-second claim on the key while the new tab starts, under `locks/viewers.lock`, so two quick `run`s never open two tabs.
- `kengash run` appends where to watch to each `started` line: `started 7add8c2e implement→antigravity (watch: orca tab kg 7add8c2e)`, or, with no terminal, `(watch: kengash logs 7add8c2e --watch)`. `--json` carries a `watch` field.

### 3.2 Terminals (`ops.terminals`)

Detected in this order from the environment of the process that opens the tab (the conductor's shell, or the UI server it started):

| Terminal | Detected by | Opens a tab with |
|---|---|---|
| a template | `watch.terminal` set | the template, `{title}` and `{command}` filled in (shell-quoted) |
| Orca | `TERM_PROGRAM=Orca` and `orca` on PATH | `orca terminal create --title <title> --command <command> --json` |
| tmux | `TMUX` set | `tmux new-window -d -n <title> <command>` |
| gnome-terminal | `DISPLAY` or `WAYLAND_DISPLAY` set and `gnome-terminal` on PATH | `gnome-terminal --tab --title=<title> -- <argv>` |
| none | | nothing; the command is printed |

The opener runs with a 10-second timeout and never fails the command that called it: a failed open is reported like "none". `KENGASH_WATCH=off` in the environment turns off every tab and notification (tests, evals, CI set it).

### 3.3 The worker tab: `kengash logs <id> --watch`

- Like `-f`, it prints every action as it happens, and keeps following through gates: a ticket that stops at `needs_approval` and is approved later goes on in the same tab. Each status change prints one line.
- It ends when the ticket is done (merged, closed or stopped for good): it prints the final status and, on a terminal, waits for Enter, so the last lines stay readable.
- It polls every second while a worker runs and every 3 seconds otherwise.

### 3.4 The dashboard: `kengash watch [-p project] [--once]`

One live screen (rich `Live`, refreshed every 2 s; Ctrl-C ends it):
- **Loops:** each live lease (agent, scope, last seen).
- **Slots:** sessions in use per CLI against the machine limits (`claude 2/3 · antigravity 1/2`), and tokens used today per CLI from the journal's `step.end` events.
- **Workers:** one row per running ticket: id, project, `step → cli/model`, elapsed, active ago, files changed, tokens used of the ticket's cap, last action; `quiet` and `worker gone` in red.
- **Needs you:** tickets at `needs_approval`, `stalled`, `failed` or `awaiting_merge`, each with its reason and the command that acts on it.
- **Feed:** the last 12 actions across all running workers, newest last, each prefixed with its ticket id.

`--once` prints the same as plain text and exits (scripts, the conductor when asked). The data is `ops.watch.board(paths, slugs) -> Board`, read without side effects; the journal is read once per refresh, and a log's tail is read again only when its size changed.

### 3.5 Notifications

- When an event `ticket.needs_approval`, `ticket.stalled`, `ticket.failed`, `ticket.awaiting_merge` or `plan.reviewed` is recorded, kengash sends one desktop notification: `kengash · <project>` / `<id> needs approval: token cap … · kengash approve <id>`.
- `notify-send` on Linux (urgency critical for `failed`), `osascript` on macOS, otherwise nothing.
- Sent from `records.record`, fire-and-forget (the process is started and never waited for), never raising. `watch.notify: false` or `KENGASH_WATCH=off` turns it off.

### 3.6 Talking to one worker: `kengash ticket attach <id> --tab`

Opens a tab running the role's session interactively (`agy --conversation …`, `claude --resume …`, `codex resume …`) in the ticket's worktree, so the user talks to exactly that agent with its full context. Refused, naming why, while a worker runs that ticket (one session cannot take two drivers). The loop resumes the same session afterwards.

### 3.7 Settings

```
watch:
  tabs: auto        # auto: a tab per worker and a dashboard per loop; off: print the command
  terminal: ""      # a command with {title} and {command}; empty: detect Orca, tmux, gnome-terminal
  notify: true      # a desktop notification when a ticket needs you
```

### 3.8 The loop skill spends less

- `references/background.md`: tabs replace background `kengash logs -f` tasks; a background `logs` task starts only when `run` printed `(watch: kengash logs …)` (no terminal found).
- On `wait` exit 3, the conductor runs `wait` again without restating the progress lines, unless a line says `quiet` or `worker gone`, or the user asks (*call*: the user sees the tabs; repeating them costs output tokens every 5 minutes).

### 3.9 Parallel work, proven

Parallel tickets already work by design (a worktree each, non-overlapping `touches`, slots per CLI, turns per project) but are tested only in the scheduler's unit tests. SP13 adds:
- an integration test that starts two tickets with disjoint `touches` in one `run`, sees both workers alive at once, and merges both; a third that overlaps one of them is held back with `touches overlap`;
- an eval scenario `loop/parallel` with two independent tickets on real CLIs, expecting both merged.

## 4. Non-goals and anti-goals

- Non-goals: agent-to-agent chat (§2.6); a model summarising progress; a daemon or a terminal multiplexer of our own; macOS Terminal/iTerm tab opening (use `watch.terminal`); a new UI screen (the UI's Overview and Live tab already show the same data).
- Anti-goals: a tab opened twice for one ticket; tabs or notifications during tests and evals; any monitoring that runs a model; a failed tab open that fails `kengash run`; transcripts in the conductor's context.

## 5. Contract changes (system spec, same commits)

- §4.1 runtime layout: `viewers/<key>.json`, `locks/viewers.lock`.
- §4.6: the `watch` section.
- §6: `kengash watch`, `kengash logs --watch`, `kengash ticket attach --tab`; `run`'s `(watch: …)` suffix.
- §8.1: the loop skill's tab and progress rules.

## 6. Milestones and exit criteria

| M | Scope | Exit |
|---|---|---|
| M1 | `ops.terminals`, viewer registry, worker and dashboard tabs opened on start and claim, `logs --watch`, `ticket attach --tab`, `watch` settings, `KENGASH_WATCH` | unit tests per terminal (argv built, env detection, template quoting, none), dedupe and claim race, `logs --watch` through a gate to done; one real tab opened in Orca on this machine |
| M2 | `ops.watch.board`, `kengash watch [--once]` | board tests (loops, slots, tokens today, workers, gates, feed); `--once` output; checked live in a terminal |
| M3 | notifications, loop skill changes, docs, CHANGELOG | notification argv per OS and the events that send one; skills lint within caps; loop evals green on claude and agy |
| M4 | parallel proof | the integration test and `loop/parallel` green on claude and agy |

Each milestone ends with a critical review against this spec (hard rule 9).

## 7. Risks

- **Tab spam with many workers.** Eight parallel workers mean eight tabs. `watch.tabs: off` keeps only the printed commands, and the dashboard covers everything in one tab.
- **A viewer left running** holds its key, so no second tab opens: it is the user's tab, still showing that ticket, which is the intent. A crashed viewer's pid is dead, so its key frees itself.
- **The opener's environment.** A conductor started outside any terminal (a cron job, an IDE without one) detects nothing and prints the commands; nothing breaks.
