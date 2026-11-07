# adapters

## Purpose

Run one step as one call to a provider CLI (SP3 spec §8): build the command line, run it in the ticket's worktree under the user's own login, and turn its output into a `StepResult`. Never touches the store.

## Interface

- `get(name, runtime=)` → `Provider`: `claude`, `codex` (schema files in `runtime/schemas/`), `antigravity`, `shell`; `gemini`, replaced by Antigravity (`model.REPLACED`), and unknown names raise `UserError`. `runtime` holds files a CLI needs on disk.
- `Provider` protocol: `name`, `detect()` → `ProviderStatus`, `run(StepRequest)` → `StepResult`, `attach_command(session_id)` (the caller runs it in the worktree), `recover_session(log)` (a killed step's session id, when the CLI printed it).
- `base.CliProvider`: shared `run` and `detect` (which also fills `models()`: the class `MODELS`, or what the sign-in check found); subclasses give `command(req)` (pure argv), `parse(req, proc)`, `signed_in()` and `attach_command`.
- `process.run_process(argv, cwd=, env=, timeout_s=, log=, grace_s=10)` → `ProcessResult(exit_code, stdout, stderr, timed_out, duration_s)`.
- `env.worker_env(environ, provider, role, allow_api_key=)`: the worker environment.
- Helpers: `positional` (argv text never starts with `-`), `classify` (`auth`, `rate_limit` or `crash` from an error message), `tail`, `schema_json`, `checked`.
- `claude.Claude`: `claude -p` with `--output-format json --json-schema`; new sessions take `--session-id` (kengash picks it) and the role skill through `--append-system-prompt`, resumes `--resume`; isolation `--setting-sources project,local --strict-mcp-config` unless `user_config`; `read_only` → `--permission-mode dontAsk` with `READ_TOOLS`, `edit_worktree` → `acceptEdits --permission-prompts none` plus the test and lint commands; bypass replaces the profile. Without claude's JSON a new session's `session_id` is None (only confirmed or resumed sessions are reported). Errors: `api_error_status` 401/403 `auth`, 429 `rate_limit` (reset time from `…|<epoch>`), else `classify(result)`. Signed in: `claude auth status --json` (`loggedIn`, `authMethod`).
- `codex.Codex(schemas)`: `codex exec --json --output-schema <file>`; new sessions `-s <sandbox>`, resumes `exec resume … -c sandbox_mode="…" <id>`; `read_only` → `read-only`, `edit_worktree` → `workspace-write`; isolation `--ignore-user-config` unless `user_config`; bypass replaces the sandbox; the skill is prepended to a new session's prompt. Events: `thread.started` gives the session (also `recover_session` from a killed step's log), the last `agent_message` holds the output JSON, `turn.completed` the usage (cached tokens move from input to cache read), `turn.failed`, and `error` events the turn did not survive, are classified. Signed in: `codex login status` exits 0.
- `antigravity.Antigravity`: `agy -p … --output-format json --json-schema …` on every turn, `--conversation <id>` to resume; `read_only` → `--mode plan` plus `READ_ONLY_LINE` at the end of the prompt, `edit_worktree` → `--mode accept-edits` plus, unless bypassed, `edit_line(...)` naming what it may run: the project's test and lint commands without a shell operator (`runnable`) and `GIT_READS`, each allowed by a `command(<cmd>)` rule in `--settings` beside `read_file(*)` (SP15); with no runnable check, `EDIT_LINE` (no terminal commands) and only the read rule; no isolation flag (`--disable-slash-commands` voids `--mode`); bypass adds `--dangerously-skip-permissions`. Output counts only when a line of `response` parses to `structured_output` (agy repeats a stale one otherwise); `denied_actions` without output is `empty`; usage is a conversation total, so `usage` = totals − `prior_usage` and `total_usage` carries the totals. Signed in: `agy models` exits 0.
- `digest.excerpt(output, command=, exit_code=, cwd=, log=)` → `Digest(headline, text, file, line)`: a failing check's marker lines (errors, failures, Expected/Actual, analyzer rows, `path:line`) with 2 lines before and 8 after, plus the last 2 non-empty lines; at most 60 lines and 4,000 characters, the cut counted in `… N more lines; full output: <log>` before the summary; no marker keeps the last 30 lines. `file:line` is the first reference to a file inside `cwd`. `digest.section(d)` is the `## Check output` body (SP15).
- `shell.Shell`: `sh -c <project.test_cmd>`, then `<project.lint_cmd>`; exit 0 passes, otherwise one `high` finding: `file:line` and headline from the digest, fix `fix the cause in Check output, then run <command>`, and `StepResult.check_output` = `digest.section(...)` (SP15); an empty command fails with "set project.test_cmd".

## Invariants

- Imports only `model`.
- Every CLI runs in its own process group (`start_new_session`); at the timeout the group gets SIGTERM, then SIGKILL after the grace period; background children left after a normal exit are ended too, and an interrupted wait (a stopped worker) ends the group within 3 s before re-raising.
- stdout goes to the request's log, stderr next to it as `.err`; output is decoded as UTF-8 with replacement characters.
- Worker environments drop `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `CODEX_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY` (except the running provider's own with `allow_api_key`), `CLAUDECODE` and `CLAUDE_CODE_ENTRYPOINT`, and set `HARNESS_AGENT=<role>`.
- A prompt plus skill over 120 KiB fails as `crash` before any CLI starts; a missing binary is a `crash` naming it.
- One call per `run`: retries, fallbacks and quota waits belong to `ops`.
- Never used: claude `--bare` and `--no-session-persistence`, codex `--ephemeral`; token files are never read.
- agy editing steps may read any file the user can (`--settings` allow `read_file(*)`, SP12 spec §5.3): agy 1.5.2 already read outside the worktree without it, and the rule only stops a denied read from ending the turn. Workers never get API keys, but whatever a model reads reaches its provider; keep secrets out of reach of the user account that runs kengash, as with any coding agent.

## Changes

- 2026-11-07: digest review fixes: a dart/flutter progress line is a marker only with `[E]` (test names hold marker words); the headline prefers a strong marker (`[E]`, FAILED, EXCEPTION, `Expected:`, `Error:`, analyzer rows); every pattern starts at a token boundary, so long lines cost linear time (100,000 long lines: 22.7 s → 0.7 s) (SP15).
- 2026-11-07: agy editing steps may run the project's checks and read-only git (`command(...)` allow rules, `edit_line`); a check with a shell operator is left out (SP15).
- 2026-11-07: `Shell` failures carry the digest: the headline as the finding, `check_output` for the ticket (SP15).
- 2026-11-07: `digest`: failure digests for check output (SP15).
- 2026-11-06 (SP12 minors): a stream that ends without a result is classified from stderr, else from `stream.said` (the CLI's lines that are not JSON and each event's `error`), never from the model's text; with neither it is a crash, `stream ended without a result (exit N)` (`base.unfinished`).
- 2026-11-06 (final review): the stdout pump stamps each line before writing it and is waited on for at most `grace_s` after the group ends, so a child that left the group holding stdout cannot hang a call; `classify` knows claude's and Node's network wording (`Connection error`, `Request timed out`, `ECONNREFUSED`, `ENOTFOUND`, `ETIMEDOUT`, `EAI_AGAIN`, `fetch failed`, `socket hang up`); `stream.lines` splits on `\n` only, keeping JSON with U+2028 whole.
- 2026-11-06: agy editing steps pass `--settings` allowing `read_file(*)`, the allow-rule agy's own denial names, so a read it cannot prompt for no longer ends the turn (SP12 M3).
- 2026-11-06: `Shell` runs `project.test_cmd`, then `project.lint_cmd` (an empty one skipped; lint logs to `<log>-lint.out`); the first failure is the verdict, its finding naming `make project.<x>_cmd pass`; summaries `tests passed`, `tests and lint passed`, `lint failed (exit N)` (SP12 M3).
- 2026-11-06: `run_process` pumps stdout through a thread into the log line by line, stamping each line in `<log>.ts` (ISO UTC), so a running worker can be watched (SP12 M2).
- 2026-11-06: claude runs `--output-format stream-json --verbose`; parse reads the last `result` event (or a single object), the session comes from `system/init` when the result lacks one, `recover_session` reads it from the log, and `is_error` with a schema-valid output is a success with `warning` (SP12 M1).
- 2026-11-06: `stream` (`lines`, `result`, `first`) reads stream-json; agy runs `--output-format stream-json`: its session comes from `init`, `recover_session` reads it from the log, a fresh schema-valid output wins over a late `ERROR` (kept as `warning`), and an error is classified from agy's `error` field and stderr (the response only when both are empty) (SP12 M1).
- 2026-11-06: `classify` knows `network` (connection resets and refusals, broken pipes, EOF, TLS and DNS failures, stream errors, HTTP 500/502/503/504, `UNAVAILABLE`, `INTERNAL`, overloaded), after `auth` and `rate_limit` (SP12 M1).
- 2026-10-30: `known_models(name)`: Claude Code's aliases without running the CLI (SP10 M4).
- 2026-10-30: `ProviderStatus.models` from `detect()` once signed in: claude's `MODELS` aliases (fable, opus, sonnet, haiku), agy's from the `agy models` sign-in check (`antigravity.parse_models`), none for codex (SP10 M3).
- 2026-10-26: workers get `KENGASH_AGENT` (SP8).
- 2026-10-26: the package is `kengash_ai` (the app is Kengash AI, distributed as `kengash-ai`; SP7 spec decision 16).
- 2026-10-26: `UNSUPPORTED` removed: Antigravity replaces gemini; `get("gemini")` names the replacement (SP7).
- 2026-10-26: `UNSUPPORTED` with the reason gemini is not driven (SP6).
- 2026-10-23: agy editing steps get `EDIT_LINE` (SP3 M4 live smoke).
- 2026-10-23: claude reports a new session only once claude confirms it (SP3 M3 review).
- 2026-10-23: an interrupted wait ends the CLI's process group (SP3 M3).
- 2026-10-23: codex `error` events followed by a completed turn are retries, not failures (SP3 M2 review).
- 2026-10-23: antigravity provider (SP3 M2).
- 2026-10-23: codex provider (SP3 M2).
