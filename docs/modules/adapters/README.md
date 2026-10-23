# adapters

## Purpose

Run one step as one call to a provider CLI (SP3 spec §8): build the command line, run it in the ticket's worktree under the user's own login, and turn its output into a `StepResult`. Never touches the store.

## Interface

- `get(name, runtime=)` → `Provider`: `claude`, `codex` (schema files in `runtime/schemas/`), `antigravity`, `shell`; `gemini` raises `NeedsSetup` (exit 4), unknown names `UserError`. `runtime` holds files a CLI needs on disk.
- `Provider` protocol: `name`, `detect()` → `ProviderStatus`, `run(StepRequest)` → `StepResult`, `attach_command(session_id)` (the caller runs it in the worktree), `recover_session(log)` (a killed step's session id, when the CLI printed it).
- `base.CliProvider`: shared `run` and `detect`; subclasses give `command(req)` (pure argv), `parse(req, proc)`, `signed_in()` and `attach_command`.
- `process.run_process(argv, cwd=, env=, timeout_s=, log=, grace_s=10)` → `ProcessResult(exit_code, stdout, stderr, timed_out, duration_s)`.
- `env.worker_env(environ, provider, role, allow_api_key=)`: the worker environment.
- Helpers: `positional` (argv text never starts with `-`), `classify` (`auth`, `rate_limit` or `crash` from an error message), `tail`, `schema_json`, `checked`.
- `claude.Claude`: `claude -p` with `--output-format json --json-schema`; new sessions take `--session-id` (harness picks it) and the role skill through `--append-system-prompt`, resumes `--resume`; isolation `--setting-sources project,local --strict-mcp-config` unless `user_config`; `read_only` → `--permission-mode dontAsk` with `READ_TOOLS`, `edit_worktree` → `acceptEdits --permission-prompts none` plus the test and lint commands; bypass replaces the profile. Errors: `api_error_status` 401/403 `auth`, 429 `rate_limit` (reset time from `…|<epoch>`), else `classify(result)`. Signed in: `claude auth status --json` (`loggedIn`, `authMethod`).
- `codex.Codex(schemas)`: `codex exec --json --output-schema <file>`; new sessions `-s <sandbox>`, resumes `exec resume … -c sandbox_mode="…" <id>`; `read_only` → `read-only`, `edit_worktree` → `workspace-write`; isolation `--ignore-user-config` unless `user_config`; bypass replaces the sandbox; the skill is prepended to a new session's prompt. Events: `thread.started` gives the session (also `recover_session` from a killed step's log), the last `agent_message` holds the output JSON, `turn.completed` the usage (cached tokens move from input to cache read), `turn.failed`, and `error` events the turn did not survive, are classified. Signed in: `codex login status` exits 0.
- `antigravity.Antigravity`: `agy -p … --output-format json --json-schema …` on every turn, `--conversation <id>` to resume; `read_only` → `--mode plan` plus `READ_ONLY_LINE` at the end of the prompt, `edit_worktree` → `--mode accept-edits`; no isolation flag (`--disable-slash-commands` voids `--mode`); bypass adds `--dangerously-skip-permissions`. Output counts only when a line of `response` parses to `structured_output` (agy repeats a stale one otherwise); `denied_actions` without output is `empty`; usage is a conversation total, so `usage` = totals − `prior_usage` and `total_usage` carries the totals. Signed in: `agy models` exits 0.
- `shell.Shell`: `sh -c <project.test_cmd>`; exit 0 passes, otherwise one `high` finding holding the last 20 output lines; an empty command fails with "set project.test_cmd".

## Invariants

- Imports only `model`.
- Every CLI runs in its own process group (`start_new_session`); at the timeout the group gets SIGTERM, then SIGKILL after the grace period; background children left after a normal exit are ended too.
- stdout goes to the request's log, stderr next to it as `.err`; output is decoded as UTF-8 with replacement characters.
- Worker environments drop `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `CODEX_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY` (except the running provider's own with `allow_api_key`), `CLAUDECODE` and `CLAUDE_CODE_ENTRYPOINT`, and set `HARNESS_AGENT=<role>`.
- A prompt plus skill over 120 KiB fails as `crash` before any CLI starts; a missing binary is a `crash` naming it.
- One call per `run`: retries, fallbacks and quota waits belong to `ops`.
- Never used: claude `--bare` and `--no-session-persistence`, codex `--ephemeral`; token files are never read.

## Changes

- 2026-10-23: codex `error` events followed by a completed turn are retries, not failures (SP3 M2 review).
- 2026-10-23: antigravity provider (SP3 M2).
- 2026-10-23: codex provider (SP3 M2).
- 2026-10-23: claude provider (SP3 M2).
- 2026-10-23: process runner, worker environment, shell provider, registry (SP3 M2).
