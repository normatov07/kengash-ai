"""Claude Code driver: `claude -p` with JSON output (SP3 spec §8.1)."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from kengash_ai.adapters import stream
from kengash_ai.adapters.base import (
    CliProvider,
    checked,
    classify,
    positional,
    probe,
    schema_json,
    tail,
    unfinished,
)
from kengash_ai.adapters.process import ProcessResult
from kengash_ai.adapters.watchdog import Signal
from kengash_ai.model import ErrorKind, StepRequest, StepResult, Usage

READ_TOOLS = (
    "Read",
    "Grep",
    "Glob",
    "Bash(git diff:*)",
    "Bash(git log:*)",
    "Bash(git show:*)",
    "Bash(git status:*)",
)
ISOLATION = ("--setting-sources", "project,local", "--strict-mcp-config")
_RESET = re.compile(r"\|(\d{10})\b")
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
POLL_TOOLS = ("BashOutput", "TaskOutput", "Monitor")


class Claude(CliProvider):
    name = "claude"
    binary = "claude"
    install_hint = "install Claude Code, then run `claude` once to sign in"
    signin_hint = "run `claude` and sign in with /login"
    MODELS = ("fable", "opus", "sonnet", "haiku")  # `--model` aliases for the latest of each

    def command(self, req: StepRequest) -> list[str]:
        argv = [self.binary, "-p", positional(req.prompt)]
        if req.resume:
            argv += ["--resume", str(req.session_id)]
        # stream-json (SP12): the log grows as claude works; the last `result` event is the output
        argv += ["--output-format", "stream-json", "--verbose"]
        argv += ["--json-schema", schema_json(req.output)]
        if not req.resume:
            argv += ["--session-id", req.session_id or str(uuid4())]
        if req.model:
            argv += ["--model", req.model]
        if req.skill and not req.resume:
            argv += ["--append-system-prompt", positional(req.skill)]
        if not req.user_config:
            argv += ISOLATION
        # --allowedTools takes several values, so the profile goes last.
        return argv + (["--dangerously-skip-permissions"] if req.bypass else _profile(req))

    def parse(self, req: StepRequest, proc: ProcessResult) -> StepResult:
        stdout = proc.stdout.strip()
        init = stream.first(stdout, key="type", value="system")
        # Without claude's output, only a resumed session, or one its stream opened, exists.
        known = (init or {}).get("session_id") or (req.session_id if req.resume else None)
        if not stdout and proc.exit_code == 0:
            return StepResult(session_id=known, error="empty", detail="no output")
        data = stream.result(stdout, key="type", value="result")
        if not isinstance(data, dict) or ("result" not in data and "is_error" not in data):
            message = unfinished(proc)
            return StepResult(session_id=known, error=classify(message), detail=message)
        session = data.get("session_id") or known or req.session_id
        text = str(data.get("result") or "")
        usage = _usage(data)
        structured = data.get("structured_output")
        failed = bool(data.get("is_error")) or proc.exit_code != 0
        if failed and structured is not None:
            output, _ = checked(req.output, structured)
            if output is not None:  # the work is done: a late error is only a warning
                warning = tail(text or proc.stderr, 3)
                return StepResult(
                    session_id=session, output=output, text=text, usage=usage, warning=warning
                )
        if failed:
            kind = _error_kind(data.get("api_error_status"), text)
            reset = _RESET.search(text) if kind == "rate_limit" else None
            return StepResult(
                session_id=session,
                text=text,
                usage=usage,
                error=kind,
                retry_after=datetime.fromtimestamp(int(reset.group(1)), UTC) if reset else None,
                detail=tail(text) or f"exit {proc.exit_code}",
            )
        if structured is None:
            return StepResult(
                session_id=session,
                text=text,
                usage=usage,
                error="schema",
                detail="no structured output",
            )
        output, problem = checked(req.output, structured)
        if output is None:
            return StepResult(
                session_id=session, text=text, usage=usage, error="schema", detail=problem
            )
        return StepResult(session_id=session, output=output, text=text, usage=usage)

    def signal(self, event: dict[str, Any]) -> Signal | None:
        if event.get("type") != "assistant":
            return None
        for block in (event.get("message") or {}).get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name")
            if name in EDIT_TOOLS:
                return Signal("edit")
            if name in POLL_TOOLS:
                return Signal("poll")
            if name == "Bash":
                return Signal("run", str((block.get("input") or {}).get("command") or ""))
        return None

    def usage_so_far(self, stdout: str) -> Usage:
        """Each assistant message's last usage; one message spans several stream events. Input
        and cache are exact; output is a floor, since the stream holds only the opening count."""
        seen: dict[str, dict[str, Any]] = {}
        for event in stream.lines(stdout):
            message = event.get("message") or {}
            if event.get("type") == "assistant" and message.get("usage"):
                seen[str(message.get("id"))] = message["usage"]
        return Usage(
            input=sum(int(u.get("input_tokens") or 0) for u in seen.values()),
            output=sum(int(u.get("output_tokens") or 0) for u in seen.values()),
            cache_read=sum(int(u.get("cache_read_input_tokens") or 0) for u in seen.values()),
            cache_write=sum(int(u.get("cache_creation_input_tokens") or 0) for u in seen.values()),
        )

    def signed_in(self) -> tuple[bool, str | None]:
        result = probe([self.binary, "auth", "status", "--json"])
        try:
            status = json.loads(result.stdout) if result else None
        except json.JSONDecodeError:
            status = None
        if not isinstance(status, dict):
            return False, None
        method = status.get("authMethod")
        return bool(status.get("loggedIn")), str(method) if method else None

    def attach_command(self, session_id: str) -> list[str]:
        return [self.binary, "--resume", session_id]

    def recover_session(self, log: Path) -> str | None:
        """The session id from the stream's `system/init` event (SP12 spec §3.5)."""
        if not log.is_file():
            return None
        text = log.read_text(encoding="utf-8", errors="replace")
        init = stream.first(text, key="type", value="system")
        session = (init or {}).get("session_id")
        return str(session) if session else None


def _profile(req: StepRequest) -> list[str]:
    if req.profile == "read_only":
        return ["--permission-mode", "dontAsk", "--allowedTools", *READ_TOOLS]
    named = (req.test_cmd, req.lint_cmd, *req.commands)
    commands = [f"Bash({cmd}:*)" for cmd in named if cmd.strip()]
    return [
        "--permission-mode",
        "acceptEdits",
        "--permission-prompts",
        "none",
        "--allowedTools",
        *READ_TOOLS,
        *commands,
    ]


def _usage(data: dict[str, Any]) -> Usage:
    usage = data.get("usage") or {}
    cost = data.get("total_cost_usd")
    return Usage(
        input=int(usage.get("input_tokens") or 0),
        output=int(usage.get("output_tokens") or 0),
        cache_read=int(usage.get("cache_read_input_tokens") or 0),
        cache_write=int(usage.get("cache_creation_input_tokens") or 0),
        cost_usd=float(cost) if cost is not None else None,
    )


def _error_kind(status: object, text: str) -> ErrorKind:
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "rate_limit"
    return classify(text)
