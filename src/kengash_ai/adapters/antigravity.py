"""Antigravity driver: `agy -p` with stream-json output (SP3 spec §8.1, live runs of
2026-10-23; SP12: streaming, a valid output wins over a late error, agy's own error field)."""

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

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
from kengash_ai.model import StepRequest, StepResult, Usage

# agy's plan mode denies terminal commands and then returns nothing; this line avoids them.
READ_ONLY_LINE = (
    "This is a read-only step: read files with your file-viewing tools only; "
    "never run terminal commands."
)
# Headless accept-edits mode denies terminal commands, and a denied first command ends the
# turn with no output (live run 2026-10-23), so editing steps are told up front.
EDIT_LINE = (
    "Terminal commands are not available in this step: read and edit files with your "
    "file tools only, and do not run tests; review steps check the result."
)
# SP15: editing steps may run the project's checks and read-only git. agy matches an allow
# rule `command(<prefix>)` against each part of a line, so a check holding a shell operator
# cannot be allowed and is left out.
GIT_READS = ("git status", "git diff", "git log", "git show")
OPERATORS = ("&&", "||", ";", "|", ">", "<", "`", "$(")
MODE = {"read_only": "plan", "edit_worktree": "accept-edits"}
# Headless agy auto-denies a read it cannot prompt for and ends the turn (chess-samurai run of
# 2026-11-06, call 3); its own message names this allow-rule. Reads only (SP12 spec §5.3).
READ_RULE = "read_file(*)"

_MODEL = re.compile(r"[A-Za-z0-9][\w.:-]*")


class Antigravity(CliProvider):
    """No isolation flag: `--disable-slash-commands` makes agy ignore `--mode`."""

    name = "antigravity"
    binary = "agy"
    install_hint = "install the Antigravity CLI (agy), then run `agy` once to sign in"
    signin_hint = "run `agy` and sign in"

    def __init__(self) -> None:
        self._models: list[str] = []

    def command(self, req: StepRequest) -> list[str]:
        text = f"{req.skill}\n\n{req.prompt}" if req.skill and not req.resume else req.prompt
        checks = runnable(req)
        allowed = [*checks, *GIT_READS] if checks else []
        if req.profile == "read_only":
            text = f"{text}\n\n{READ_ONLY_LINE}"
        elif not req.bypass:
            text = f"{text}\n\n{edit_line(allowed) if allowed else EDIT_LINE}"
        argv = [self.binary, "-p", positional(text)]
        if req.resume:
            argv += ["--conversation", str(req.session_id)]
        # Every turn passes the schema: without it agy repeats the previous output.
        argv += ["--output-format", "stream-json", "--json-schema", schema_json(req.output)]
        if req.model:
            argv += ["--model", req.model]
        argv += ["--mode", MODE[req.profile]]
        if req.profile == "edit_worktree":
            rules = [READ_RULE, *[f"command({command})" for command in allowed]]
            argv += ["--settings", json.dumps({"permissions": {"allow": rules}})]
        return argv + (["--dangerously-skip-permissions"] if req.bypass else [])

    def parse(self, req: StepRequest, proc: ProcessResult) -> StepResult:
        stdout = proc.stdout.strip()
        if not stdout and proc.exit_code == 0:
            return StepResult(session_id=req.session_id, error="empty", detail="no output")
        init = stream.first(stdout, key="event", value="init")
        started = (init or {}).get("conversation_id") or req.session_id
        event = stream.result(stdout, key="event", value="result")
        data = (
            event.get("result") if event is not None and event.get("event") == "result" else event
        )
        if not isinstance(data, dict) or "status" not in data:
            # no result: the CLI died mid-stream; classify what it said, never `empty`
            message = unfinished(proc)
            return StepResult(session_id=started, error=classify(message), detail=message)
        text = str(data.get("response") or "")
        totals = _totals(data.get("usage") or {})

        def result(**fields: Any) -> StepResult:
            return StepResult(
                session_id=data.get("conversation_id") or started,
                text=text,
                usage=totals.minus(req.prior_usage),
                total_usage=totals,
                **fields,
            )

        failed = data.get("status") != "SUCCESS" or proc.exit_code != 0
        structured = data.get("structured_output")
        if structured is not None and _fresh(text, structured):
            output, problem = checked(req.output, structured)
            if output is not None:  # the work is done: a late error is only a warning
                warning = str(data.get("error") or proc.stderr.strip()) if failed else ""
                return result(output=output, warning=tail(warning, 3))
            if not failed:
                return result(error="schema", detail=problem)
        if failed:
            # agy's own error and stderr; the response is the model's text (agy 1.4 put its
            # error there, so it is read only when nothing else says why)
            said = "\n".join(str(part) for part in (data.get("error"), proc.stderr) if part)
            message = said.strip() or text
            return result(error=classify(message), detail=tail(message) or f"exit {proc.exit_code}")
        if structured is None:
            denied = [
                str(action.get("display_name") or action.get("action"))
                for action in data.get("denied_actions") or []
                if isinstance(action, dict)
            ]
            detail = f"no output; denied: {', '.join(denied)}" if denied else "no output"
            return result(error="empty", detail=detail)
        return result(error="schema", detail="agy repeated the previous turn's output")

    def signed_in(self) -> tuple[bool, str | None]:
        result = probe([self.binary, "models"])
        ok = result is not None and result.returncode == 0
        self._models = parse_models(result.stdout) if result is not None and ok else []
        return ok, None

    def models(self) -> list[str]:
        return list(self._models)

    def attach_command(self, session_id: str) -> list[str]:
        return [self.binary, "--conversation", session_id]

    def recover_session(self, log: Path) -> str | None:
        """The conversation id from the stream's `init` event (SP12 spec §3.5)."""
        if not log.is_file():
            return None
        init = stream.first(
            log.read_text(encoding="utf-8", errors="replace"), key="event", value="init"
        )
        conversation = (init or {}).get("conversation_id")
        return str(conversation) if conversation else None


def runnable(req: StepRequest) -> list[str]:
    """The project's test and lint commands an agy rule can allow: set, with no operator."""
    commands = (req.test_cmd.strip(), req.lint_cmd.strip())
    return [c for c in commands if c and not any(op in c for op in OPERATORS)]


def edit_line(commands: Sequence[str]) -> str:
    """What an editing step is told it may run (SP15 spec §3.5)."""
    listed = ", ".join(f"`{command}`" for command in commands)
    return (
        "You may run only these terminal commands, each on its own with no &&, ;, pipes or "
        f"redirects: {listed}. Any other command ends your turn; read and edit files with "
        "your file tools."
    )


def parse_models(stdout: str) -> list[str]:
    """The model ids `agy models` lists, one `<id>\t<label>` per line after a progress line."""
    found: list[str] = []
    for line in stdout.splitlines():
        name = line.split("\t", 1)[0].strip()
        if name and _MODEL.fullmatch(name):
            found.append(name)
    return found


def _totals(usage: dict[str, Any]) -> Usage:
    """Conversation totals; agy reports cache reads apart from `input_tokens`."""
    return Usage(
        input=int(usage.get("input_tokens") or 0),
        output=int(usage.get("output_tokens") or 0),
        cache_read=int(usage.get("cache_read_tokens") or 0),
    )


def _fresh(response: str, structured: object) -> bool:
    """True when this turn's text carries the structured output, so it is not a stale repeat."""
    candidates = [response, *reversed(response.splitlines())]
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate.startswith("{"):
            continue
        try:
            if json.loads(candidate) == structured:
                return True
        except json.JSONDecodeError:
            continue
    return False
