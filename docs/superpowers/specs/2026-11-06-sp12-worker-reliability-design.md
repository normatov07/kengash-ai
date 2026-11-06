# SP12: Worker reliability and visibility (design)

Date: 2026-11-06. Status: written from the user's report of the same day and an investigation of their store; builder-checked; the user chose two decisions (§5.2 old values, §5.5 checks step); calls marked *call* are the builder's and open to veto.

## 1. Why

The user, on 2026-11-06 (kengash 0.3.0, project chess-samurai). Planner and plan reviewer ran on claude/opus, the implementer on antigravity/gemini-3.8-flash-medium. One ticket ran plan → review_plan → implement. During implement, the Claude Code conductor ran `kengash wait` again and again for over 20 minutes and showed nothing. Nothing showed whether agy was alive, and nothing changed in the repo. Then the ticket failed. The user asks why we cannot see what the worker CLIs are doing, and why the run failed. They want both fixed with best practices.

Evidence from `~/.kengash`:
- Ticket `7add8c2e`.
- `runtime/logs/7add8c2e-{3,4}.{out,err}`.
- The journal of 2026-11-06.
- The worktree `worktrees/chess-samurai/kg-7add8c2e`.

What it shows:

1. **Good work was thrown away.**
   - Call 4 ran 1,283 s and ended in `{"status":"ERROR", "error":"API error (attempt 1): … read: connection reset by peer", "structured_output":{…valid handoff and summary…}}`.
   - agy had finished the edits: the worktree holds 26 changed files. It had also produced the schema output. Only the final network stream failed.
   - `adapters/antigravity.py` treats any status other than `SUCCESS` as an error before it looks at `structured_output`. The ticket failed as `crash: {…the whole JSON…}`, and the edits stayed uncommitted.
2. **agy's own error is never read.** The adapter classifies the model's response text plus stderr, never agy's `error` field. So a quota or network error that agy reports there is invisible. A response that merely says "quota" or "401" would be misread.
3. **Network errors are fatal.**
   - `adapters.classify` knows only `auth` and `rate_limit`; everything else is `crash`.
   - `crash` is never retried, and it never reaches the fallback agent: claude/sonnet was configured but unused.
4. **The retry would start blind.**
   - The implementer's agy session id is stored only after a step succeeds, so a retry starts a fresh session. That session does not know that 26 files were already changed.
   - The failure line does not say where the work is. The user looked at their repo, not the worktree.
5. **Nothing reports progress.**
   - `kengash wait` blocks for up to 540 s and then prints only `wait timed out after 540 s`.
   - The worker CLIs write JSON only when they end, so the log stays empty for the whole step.
   - Nothing reports how long a step has run, whether its process is alive, what it last did, or which files changed in its worktree.
6. **Smaller gaps.**
   - The ticket was at 505,494 tokens against a 250,000 cap: agy reports 439,906 fresh input tokens for one long implement session. So every agy implement step on a real repo stops at the cap.
   - `project.test_cmd` and `lint_cmd` are empty, so `flutter analyze` and `flutter test` never run.
   - Call 3 lost a turn because agy's headless mode auto-denied `read_file`.
   - The doc-writer runs on antigravity with no fallback.

A probe of agy 1.5.2 on 2026-11-06 found `--output-format stream-json`. It emits:
- `init`, carrying the conversation id at once;
- `step_update` events, each naming the tool and its parameters (for example `read_file` and a path);
- a final `result` with the same fields as `json`.

agy also takes `--settings <json>` for one session. Claude Code has `--output-format stream-json` (with `--verbose`). Codex's `exec --json` already streams JSONL.

## 2. Goals, non-goals, anti-goals

- Goal: a step whose CLI finished the work and returned a valid output never fails because of a network error after that.
- Goal: a transient network error is retried on the same session once, then sent to the agent's fallback, then reported in one clear line that says where the work is.
- Goal: while a step runs, the conductor and the user see what it is doing at least every 5 minutes: step, CLI and model, elapsed time, last activity, last action and changed files. The UI shows the same.
- Goal: a new project gets its test and lint commands detected, and `doctor` names any project that has none.
- Non-goals: a daemon or a terminal multiplexer; a real Claude Code subagent per worker (§4.4); showing the worker's full transcript in the conductor's context (it costs tokens; background `kengash logs -f`, which the user opens, and the UI Live tab are for that); parallel branches; Codex live verification (codex is not installed here).
- Anti-goals:
  - accepting an output that fails the step schema;
  - retrying an `auth` error, or retrying without limit;
  - any API key or OAuth token in a worker (hard rule 6);
  - a conductor wait so chatty that it floods the conductor's context;
  - a worker killed merely for being quiet.

## 3. Decisions: reliability (milestone 1)

1. **Trust a valid output.** When agy, or any adapter, returns a non-success status together with a structured output that is fresh and passes the step's schema, the result is a success. Its `warning` field carries the CLI's error text, which is journaled on `step.end` and written to the ticket's Log line.
2. **Classify the CLI's error, not the model's text.**
   - The agy adapter classifies `data["error"]` plus stderr.
   - The claude adapter keeps `is_error` with its `result` text, as today, since claude puts its errors there.
   - The model's response text is never classified.
3. **A new error kind, `network`.** `adapters.classify` recognises transient transport failures, in any case:
   - `connection reset`, `connection refused`, `broken pipe`, `ECONNRESET`, `EOF`;
   - `TLS handshake`, `no such host`, `temporary failure in name resolution`, `network is unreachable`, `stream error`;
   - HTTP `500`, `502`, `503`, `504`, `UNAVAILABLE`, `INTERNAL`, `overloaded`.

   `auth` and `rate_limit` are checked first.
4. **Handling `network`** in `ops.steps._call`, including the commit-hook repair turn, which calls the adapter directly today (`steps.py` `_commit`). `ops.calls.call`, used by plan reviews and compaction, gets only the resumed turn, then fails (*call*: the plan reviewer is chosen once per review, avoiding the conductor's provider, and the compactor has no chain):
   - First, one resumed turn on the same session, with the prompt "Your last turn was cut off by a network error. Your edits are kept; finish the step and reply."
   - Then, when the agent has a fallback and `fallback_on_error` is true, the next provider in the agent's chain, as `rate_limit` does today.
   - Otherwise, a failure.

   `fallback_on_rate_limit` is renamed `fallback_on_error`, covering rate limits and network errors; the old key is still read (*call*: one switch for "use my fallbacks when the main CLI cannot answer").
5. **Keep the session.** A failed call stores `result.session_id` on the ticket, which agy reports even with `status: ERROR`. For a killed call, `recover_session(log)` reads the id from the stream log's first event: agy's `init`, claude's `system/init`, codex's `thread.started`. The existing dead-worker recovery uses the same function. A later `kengash run <id>` then resumes the session that holds the context. The id is not stored while the step runs (*call*: nothing attaches to a running step, and `run_process` blocks until the CLI exits). Because of this, the stream-json switch of §4.1 lands in this milestone.
6. **Say where the work is.** A failure line becomes one line of at most 300 characters: `<kind>: <first line of the detail>; log: <path>`. For an editing step it adds `; work kept in <worktree> (N files changed)`. A retry of an editing step whose worktree has uncommitted changes tells the session, or a new one, that the worktree already holds changes from the failed attempt, which it should review and finish.

## 4. Decisions: visibility (milestone 2)

1. **Stream worker output** (built in milestone 1, see §3.5). Workers run claude with `--output-format stream-json --verbose` and agy with `--output-format stream-json`. Codex already streams. Adapters parse the last `result` event, so the log file grows while the step runs.
   - When no `result` event arrives, the adapter classifies stderr and the stream's last error event, as it classifies an unparseable stdout today. A network failure therefore stays `network`, never `empty`.
   - `ops.calls` stays as it is.
   - `state.running.log` names the current attempt's log: every retry and repair turn updates it. `state.running` is cleared when a step ends, passes or fails, so it means "running" and progress reads the right file. Today it is set once and left behind (`steps.py` `_prepare`).
2. **Progress, read without side effects.** `ops.progress.running(paths, slugs)` gives one `Progress` per running ticket:
   - `id`, `project`, `step`, `provider`, `model`;
   - `elapsed_s` since its `step.start`;
   - `alive`: the worker record exists, its pid runs, and its heartbeat is fresh;
   - `active_s`: seconds since the step's log, or any changed file in the worktree, was last written;
   - `action`: the last tool call in the log, for example `edit lib/main.dart` or `read pubspec.yaml`, parsed per provider;
   - `changed`: uncommitted files in the worktree, from `git status --porcelain`.

   A step quiet for 10 minutes or more is marked `quiet` (*call*). Nothing is killed for that; `step_timeout_min` still governs.
3. **`wait` shows progress.**
   - The default `--timeout` drops from 540 to 300 seconds (*call*: the conductor and user hear something every 5 minutes, inside every agent's tool timeout).
   - On exit 3, `wait` prints one line per running ticket in scope, at most 5 lines: `<id> <step>→<provider>/<model> <elapsed> · active <age> ago · <N> files changed · <action>`, ending with `· quiet` when marked.
   - The loop skill shows these lines to the user and waits again.
   - `--json` gives the `Progress` list.
4. **Each worker as a watchable "sub-agent"** (the user's request of 2026-11-06: see the worker CLIs like Claude Code's or Antigravity's subagents, and click one to see what it does).
   - **What is not possible, and why.** A worker cannot become a real Claude Code subagent: the Agent tool runs Claude models only. A Claude "watcher" subagent per ticket would spend tokens re-reading every event, and its transcript would show its own tool calls, not agy's. So kengash streams the worker's own actions to the places the user already clicks. That costs no tokens, keeps the conductor free, and works with any conductor (*call*).
   - **`kengash logs <id> -f`: the worker's live transcript.**
     - It follows one ticket across all its steps, one readable line per worker action, parsed from the stream logs (§4.1):
       ```
       11:05:43 implement → antigravity/gemini-3.8-flash-medium (session d68cea60)
       11:05:51 read pubspec.yaml
       11:06:02 edit lib/main.dart
       11:26:27 reply: Rebrand core package and UI to Chess Samurai
       11:26:30 implement done · 26 files changed · 498k tokens
       11:26:31 review_code → claude/opus
       ```
     - Without `-f` it prints what has happened so far. With `-f` it ends when the ticket reaches a gate, is done or fails, with a closing status line. `--json` gives the events.
   - **In the conductor: background tasks, not a silent wait.** The loop skill gains `references/background.md`, read "when your shell can run a command in the background and tell you when it ends" (Claude Code's background commands; *call*: a reference, because the skill is at its word cap and other agents lack the feature). It says:
     - After `kengash run`, start `kengash logs <id> -f` in the background for each started ticket. The host lists each as a running task named after the ticket, and the user opens it to watch that worker live, the way a subagent's transcript opens. It ends on its own when the ticket stops.
     - Run `kengash wait` in the background too, and keep answering the user while it runs. Act on its events when the host reports that it ended. The session is never frozen in a blocking call.
     - Agents without background commands keep today's blocking `wait`, which now prints progress every 5 minutes (§4.3).
   - **`kengash ps`.** Prints one progress line per running ticket (§4.2), or `nothing running`. `--line` prints one compact line for a status bar: `kg: 2 running · 7add8c2e implement→agy 12m edit lib/main.dart`, for example from Claude Code's `statusLine` command. The docs show how to set it up; kengash never edits the user's agent settings (*call*).
5. **UI: the worker live view.**
   - Overview's Live agent sessions table gains an "activity" cell: `active <age> ago · <N> files · <action>`, red when quiet.
   - Clicking a running session opens its ticket on a new **Live** tab. It shows the same timeline as `kengash logs`: each action a row with time, kind icon (read, edit, run, reply) and target. It streams over SSE from `GET /api/tickets/{id}/live`, follows the newest row, and shows a pulsing "running" header with step, CLI and model, elapsed time and changed files.
   - Board cards of running tickets show a small pulsing dot. Clicking the card opens the Live tab.
   - The ticket sheet's changes tab lists the worktree's uncommitted files under "in progress" while a step runs.
   - The data comes from `ops.progress` and a shared log parser (`ops.activity`), which the CLI and the UI both use.

## 5. Decisions: setup (milestone 3)

1. **Detect project commands.** `ops.projects.detect_commands(repo)` returns `(test_cmd, lint_cmd)`:

   | Project | test_cmd | lint_cmd |
   |---|---|---|
   | Flutter (`pubspec.yaml` naming `flutter`) | `flutter test` | `flutter analyze` |
   | Dart | `dart test` | `dart analyze` |
   | Python with `uv.lock` | `uv run pytest -q` | `uv run ruff check` (when ruff is configured) |
   | Node (`package.json` scripts `test`, `lint`) | `npm test` | `npm run lint` |
   | Go | `go test ./...` | `go vet ./...` |
   | Rust | `cargo test` | `cargo clippy` |

   - `kengash init` writes the detected values into the new project's empty keys.
   - `kengash doctor` warns `project <slug> has no test command; detected: <cmd>; run: kengash doctor --fix` (or `set project.test_cmd` when nothing is detected).
   - `doctor --fix` writes detected values into empty keys only, through `settings.set_values`.
   - When test or lint commands are found, `kengash init` switches on the `test-runner` agent and adds `run_tests` right after `implement` in the `standard` and `critical` workflows. `doctor --fix` does the same for an existing project that has commands but no `run_tests` in those workflows (the user's choice, §5.5).
2. **Token cap and old defaults.**
   - The package default `tokens.per_ticket_max` rises from 250,000 to 1,000,000 (*call*: the evidence shows one agy implement step using 440,000 fresh input tokens; a cap every real step trips protects nothing).
   - `kengash init` copies the package SETTINGS.md into every store and project, so existing files hold the old defaults literally. `kengash doctor` lists each value that still equals an old package default:
     - `tokens.per_ticket_max: 250000`;
     - a doc-writer without `fallback`;
     - `fallback_on_rate_limit`.
   - `doctor --fix` rewrites exactly those, keeping comments: 1,000,000, `fallback: [claude/sonnet]`, and `fallback_on_error` with the same value. A value the user changed is never touched (the user's choice).
   - The `needs_approval` detail reads `token cap: 505,494 of 250,000 used; approve with: kengash approve <id> --tokens N`.
3. **agy permissions.** Editing steps pass `--settings` allowing agy's read-only file tools anywhere, so a read outside the worktree no longer ends a turn. The exact key is to be confirmed by a probe at build time; if agy offers no such key, the repair turn of SP3 stays the remedy (*call*).
5. **A checks step that runs** (the user's choice).
   - The shell adapter's `run_tests` runs `project.test_cmd`, then `project.lint_cmd`, in the worktree. It passes only when both exit 0; an empty command is skipped.
   - A failure is a `fail` verdict whose finding quotes the failing command and the tail of its output. The workflow's `on_fail` edge sends the ticket back to `implement`: the seeded workflows add `run_tests: implement`, and `doctor --fix` adds it with the step.
   - Read-only reviewers still get both commands in their prompt, as context only.
6. **Fallbacks in the defaults.** The seeded `doc-writer` gains `fallback: [claude/sonnet]`, like the implementer. `kengash doctor` notes an agent that is switched on and has no fallback, as information, not a warning (*call*).

## 6. Contract changes (system spec, same commits as the code)

- §4.6:
  - `fallback_on_error`, which replaces `fallback_on_rate_limit`; the old key is still read;
  - the `tokens.per_ticket_max` default;
  - the doc-writer fallback.
- §5 item 5, error handling:
  - `network`: a resumed turn, then the fallback, then a failure;
  - a valid output wins over a CLI error.
- §6:
  - the `wait` default timeout and its progress lines on exit 3;
  - the rows `kengash ps`, `kengash logs`;
  - `doctor`'s project-command check.
- §7.2: stream-json for claude and agy; the session id comes from the first event.

## 7. Milestones and exit criteria

| M | Scope | Exit |
|---|---|---|
| M1 | §3: valid output wins, error-field classification, `network` kind with retry and fallback, session id kept, one-line failures with the worktree | unit tests reproducing `7add8c2e-4.out` (ERROR with a valid output → success; network error without output → resume, then fallback, then failure naming the worktree) |
| M2 | §4: `ops.progress`, `ops.activity`, `wait` progress, `ps [--line]`, `logs [-f]`, the loop skill's background reference, the UI Live tab and activity cells | adapter tests on recorded stream fixtures (agy probe of 2026-11-06, claude, codex); live smoke green on claude and agy; UI checked at 360 and 1440 px |
| M3 | §5: command detection, the checks step, doctor and its fixes for old defaults, token default, agy permissions, fallbacks; docs | tests per detector, for `run_tests` (test then lint, either failing), and for doctor's old-default fixes keeping comments; `make check`; live probe for the agy `--settings` key |

Each milestone ends with a critical review against this spec (hard rule 9).

## 8. Risks

- **Stream formats can change.** Parsers read only the fields they need. An event they do not know is skipped. When no `result` event is found, the step is an `empty` error, as today.
- **Large logs.** A step that streams for 30 minutes may write megabytes. `logs.keep_days` already rotates logs; progress reads only the log's tail (*call*: the last 64 KiB).
- **`git status` cost on big worktrees.** It runs only when progress is asked for: on `wait` exit 3, `ps`, and UI reloads. Worktrees with no file written for 60 s reuse the last result.
