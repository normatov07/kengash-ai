"""Claude Code driver: `claude -p` with JSON output (SP3 spec §8.1)."""

import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from kengash_ai.adapters.base import (
    CliProvider,
    checked,
    classify,
    positional,
    probe,
    schema_json,
    tail,
)
from kengash_ai.adapters.process import ProcessResult
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


class Claude(CliProvider):
    name = "claude"
    binary = "claude"
    install_hint = "install Claude Code, then run `claude` once to sign in"
    signin_hint = "run `claude` and sign in with /login"

    def command(self, req: StepRequest) -> list[str]:
        argv = [self.binary, "-p", positional(req.prompt)]
        if req.resume:
            argv += ["--resume", str(req.session_id)]
        argv += ["--output-format", "json", "--json-schema", schema_json(req.output)]
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
        # Without claude's JSON, only a resumed session is known to exist.
        known = req.session_id if req.resume else None
        if not stdout and proc.exit_code == 0:
            return StepResult(session_id=known, error="empty", detail="no output")
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            data = None
        if not isinstance(data, dict):
            message = tail(proc.stderr or proc.stdout) or f"exit {proc.exit_code}"
            return StepResult(session_id=known, error=classify(message), detail=message)
        session = data.get("session_id") or req.session_id
        text = str(data.get("result") or "")
        usage = _usage(data)
        if data.get("is_error") or proc.exit_code != 0:
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
        structured = data.get("structured_output")
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


def _profile(req: StepRequest) -> list[str]:
    if req.profile == "read_only":
        return ["--permission-mode", "dontAsk", "--allowedTools", *READ_TOOLS]
    commands = [f"Bash({cmd}:*)" for cmd in (req.test_cmd, req.lint_cmd) if cmd.strip()]
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
