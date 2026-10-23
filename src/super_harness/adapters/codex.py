"""Codex driver: `codex exec --json` events (SP3 spec §8.1)."""

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from super_harness.adapters.base import (
    CliProvider,
    checked,
    classify,
    positional,
    probe,
    schema_json,
    tail,
)
from super_harness.adapters.process import ProcessResult
from super_harness.model import OutputKind, StepRequest, StepResult, Usage

SANDBOX = {"read_only": "read-only", "edit_worktree": "workspace-write"}


class Codex(CliProvider):
    name = "codex"
    binary = "codex"
    install_hint = "install the Codex CLI (npm i -g @openai/codex), then run `codex login`"
    signin_hint = "run `codex login`"

    def __init__(self, schemas: Path) -> None:
        self.schemas = schemas

    def schema_file(self, kind: OutputKind) -> Path:
        """The output schema as a file, as `--output-schema` needs; rewritten only on change."""
        path = self.schemas / f"{kind}.json"
        content = schema_json(kind)
        if not path.is_file() or path.read_text(encoding="utf-8") != content:
            path.parent.mkdir(parents=True, exist_ok=True)
            partial = path.with_name(f".{path.name}.{os.getpid()}")
            partial.write_text(content, encoding="utf-8")
            partial.replace(path)
        return path

    def command(self, req: StepRequest) -> list[str]:
        sandbox = SANDBOX[req.profile]
        argv = [self.binary, "exec", *(["resume"] if req.resume else [])]
        argv += ["--json", "--output-schema", str(self.schema_file(req.output))]
        if req.bypass:
            argv.append("--dangerously-bypass-approvals-and-sandbox")
        elif req.resume:
            argv += ["-c", f'sandbox_mode="{sandbox}"']  # resume takes no -s
        else:
            argv += ["-s", sandbox]
        if req.model:
            argv += ["-m", req.model]
        if not req.user_config:
            argv.append("--ignore-user-config")
        if req.resume:
            argv.append(str(req.session_id))
        text = f"{req.skill}\n\n{req.prompt}" if req.skill and not req.resume else req.prompt
        return [*argv, positional(text)]

    def parse(self, req: StepRequest, proc: ProcessResult) -> StepResult:
        session = req.session_id
        message: str | None = None
        failure: str | None = None
        usage = Usage()
        for event in _events(proc.stdout):
            kind = event.get("type")
            if kind == "thread.started":
                session = str(event.get("thread_id") or session)
            elif kind == "item.completed":
                item = event.get("item") or {}
                if item.get("type") == "agent_message":
                    message = str(item.get("text") or "")
            elif kind == "turn.completed":
                usage = _add(usage, event.get("usage") or {})
                failure = None  # an earlier `error` event was a retry the turn survived
            elif kind == "error":
                failure = str(event.get("message") or "error")
            elif kind == "turn.failed":
                failure = str((event.get("error") or {}).get("message") or "turn failed")
        if failure is not None:
            return StepResult(
                session_id=session, usage=usage, error=classify(failure), detail=tail(failure)
            )
        if message is None:
            if proc.exit_code == 0:
                return StepResult(
                    session_id=session, usage=usage, error="empty", detail="no output"
                )
            detail = tail(proc.stderr) or f"exit {proc.exit_code}"
            return StepResult(
                session_id=session, usage=usage, error=classify(detail), detail=detail
            )
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return StepResult(
                session_id=session,
                text=message,
                usage=usage,
                error="schema",
                detail="the agent message is not JSON",
            )
        output, problem = checked(req.output, data)
        if output is None:
            return StepResult(
                session_id=session, text=message, usage=usage, error="schema", detail=problem
            )
        return StepResult(session_id=session, output=output, text=message, usage=usage)

    def signed_in(self) -> tuple[bool, str | None]:
        result = probe([self.binary, "login", "status"])
        return result is not None and result.returncode == 0, None

    def attach_command(self, session_id: str) -> list[str]:
        return [self.binary, "resume", session_id]

    def recover_session(self, log: Path) -> str | None:
        """The thread id codex prints first, so a killed step can resume its session."""
        if not log.is_file():
            return None
        for event in _events(log.read_text(encoding="utf-8", errors="replace")):
            if event.get("type") == "thread.started" and event.get("thread_id"):
                return str(event["thread_id"])
        return None


def _events(text: str) -> Iterator[dict[str, Any]]:
    """JSON objects, one per line; other lines are skipped."""
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            yield event


def _add(usage: Usage, turn: dict[str, Any]) -> Usage:
    """`turn`'s tokens added; codex counts cached tokens inside `input_tokens`."""
    cached = int(turn.get("cached_input_tokens") or 0)
    return Usage(
        input=usage.input + max(int(turn.get("input_tokens") or 0) - cached, 0),
        output=usage.output + int(turn.get("output_tokens") or 0),
        cache_read=usage.cache_read + cached,
    )
