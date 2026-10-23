# Provider fixtures

Raw stdout the fake CLIs (`tests/fakes/bin/`) replay. Recorded files come from real runs on a scratch repo holding `a.py` with `x=1`; synthetic files follow a documented or observed shape and are re-checked by the live smoke (SP3 M4).

| File | Source |
|---|---|
| `claude/review_new.json` | recorded 2026-10-23, claude 2.1.309, haiku, new session, `read_only` |
| `claude/work_resume.json` | recorded 2026-10-23, same session resumed, `edit_worktree` |
| `claude/auth_error.json` | synthetic: `review_new.json` with `is_error`, `api_error_status: 401` |
| `claude/usage_limit.json` | synthetic: `review_new.json` with `is_error`, `api_error_status: 429`, a reset time |
| `codex/*.jsonl` | synthetic, from the Codex non-interactive `--json` event docs (codex is not installed on the dev machine) |
| `agy/review_new.json` | recorded 2026-10-23, agy 1.4.5, `--mode plan` with the read-only line; two local paths in `response` anonymised |
| `agy/work_resume.json` | recorded 2026-10-23, same conversation resumed, `--mode accept-edits`; usage is a conversation total |
| `agy/stale_output.json` | recorded 2026-10-23, same conversation; no schema JSON this turn, so `structured_output` repeats the previous turn |
| `agy/denied.json` | recorded 2026-10-23, `--mode plan` asked to edit: `denied_actions`, no output |
| `agy/error.json` | synthetic: a non-`SUCCESS` status |

Never record `claude auth status`: it prints the account's email and organisation.

## Re-recording

In a scratch git repo, with `env -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT`; `$REVIEW` and `$WORK` are `super_harness.adapters.base.schema_json("review")` and `("work")`, and `$READ` is `Read Grep Glob "Bash(git diff:*)" "Bash(git log:*)" "Bash(git show:*)" "Bash(git status:*)"`:

```bash
claude -p "Review a.py. Fail it with one low finding: variable name x is unclear." --output-format json --json-schema "$REVIEW" --session-id "$(uuidgen)" --model haiku --setting-sources project,local --strict-mcp-config --permission-mode dontAsk --allowedTools $READ > claude/review_new.json
claude -p "Loop 2, step implement: rename x in a.py to retry_count. Do not commit." --resume <that id> --output-format json --json-schema "$WORK" --model haiku --setting-sources project,local --strict-mcp-config --permission-mode acceptEdits --permission-prompts none --allowedTools $READ > claude/work_resume.json
agy -p "Review a.py. Fail it with one low finding: variable name x is unclear.

This is a read-only step: read files with your file-viewing tools only; never run terminal commands." --output-format json --json-schema "$REVIEW" --mode plan > agy/review_new.json
agy -p "Loop 2, step implement: rename x in a.py to retry_count. Do not commit." --conversation <its conversation_id> --output-format json --json-schema "$WORK" --mode accept-edits > agy/work_resume.json
agy -p "Reply now without using any tools: summary ok, handoff ok." --conversation <same id> --output-format json --json-schema "$WORK" --mode plan > agy/stale_output.json
agy -p "Edit a.py now: change x=1 to retry_count=1. Then report." --output-format json --json-schema "$WORK" --mode plan > agy/denied.json
```
