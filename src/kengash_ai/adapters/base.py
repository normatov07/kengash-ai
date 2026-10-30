"""The `Provider` protocol and what every CLI driver shares (SP3 spec §8.1)."""

import json
import os
import re
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from kengash_ai.adapters.env import worker_env
from kengash_ai.adapters.process import ProcessResult, run_process
from kengash_ai.model import (
    OUTPUT_SCHEMAS,
    ErrorKind,
    OutputKind,
    ProviderStatus,
    StepOutput,
    StepRequest,
    StepResult,
    parse_output,
)

MAX_PROMPT_BYTES = 120 * 1024
DETECT_TIMEOUT_S = 20
_AUTH = re.compile(
    r"(?i)not logged in|/login\b|invalid api key|unauthori[sz]ed|authenticat|sign in|\b40[13]\b"
)
_RATE = re.compile(
    r"(?i)usage limit|rate limit|limit reached|too many requests|quota|resource_exhausted|\b429\b"
)
_VERSION = re.compile(r"\d+\.\d+(?:\.\d+)?")


class Provider(Protocol):
    name: str

    def detect(self) -> ProviderStatus: ...
    def run(self, req: StepRequest) -> StepResult: ...
    def attach_command(self, session_id: str) -> list[str]: ...
    def recover_session(self, log: Path) -> str | None: ...


def positional(text: str) -> str:
    """`text` as an argv value that no CLI reads as a flag."""
    return "\n" + text if text.startswith("-") else text


def classify(text: str) -> ErrorKind:
    """An error message's kind: `auth`, `rate_limit`, else `crash`."""
    if _AUTH.search(text):
        return "auth"
    if _RATE.search(text):
        return "rate_limit"
    return "crash"


def tail(text: str, lines: int = 20) -> str:
    return "\n".join(text.rstrip("\n").splitlines()[-lines:])


def schema_json(kind: OutputKind) -> str:
    return json.dumps(OUTPUT_SCHEMAS[kind], separators=(",", ":"))


def checked(kind: OutputKind, data: object) -> tuple[StepOutput | None, str]:
    """The parsed output, or None and the `schema` error's detail."""
    try:
        return parse_output(kind, data), ""
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        reason = f"{where}: {first['msg']}" if where else first["msg"]
        return None, f"output does not match the {kind} schema: {reason}"


def timed_out(req: StepRequest, proc: ProcessResult) -> StepResult:
    return StepResult(
        session_id=req.session_id,
        error="timeout",
        detail=f"killed after {req.timeout_s} s",
        duration_s=proc.duration_s,
    )


def probe(argv: list[str]) -> subprocess.CompletedProcess[str] | None:
    """Run a status command; None when it cannot start or hangs."""
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=DETECT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


class CliProvider(ABC):
    """A provider CLI: subclasses build argv, parse output and check the sign-in."""

    name: str
    binary: str
    install_hint: str
    signin_hint: str
    MODELS: tuple[str, ...] = ()  # the model names the CLI takes, when they are fixed

    @abstractmethod
    def command(self, req: StepRequest) -> list[str]: ...

    @abstractmethod
    def parse(self, req: StepRequest, proc: ProcessResult) -> StepResult: ...

    @abstractmethod
    def signed_in(self) -> tuple[bool, str | None]:
        """(signed in, auth method when the CLI reports one)."""

    @abstractmethod
    def attach_command(self, session_id: str) -> list[str]: ...

    def recover_session(self, log: Path) -> str | None:
        return None

    def models(self) -> list[str]:
        """Model names for `--model`, offered in the UI's pickers; read after `signed_in`."""
        return list(self.MODELS)

    def run(self, req: StepRequest) -> StepResult:
        size = len(req.prompt.encode()) + len((req.skill or "").encode())
        if size > MAX_PROMPT_BYTES:
            detail = f"prompt is {size // 1024} KiB; the limit is {MAX_PROMPT_BYTES // 1024} KiB"
            return StepResult(session_id=req.session_id, error="crash", detail=detail)
        if shutil.which(self.binary) is None:
            detail = f"{self.binary} not found on PATH"
            return StepResult(session_id=req.session_id, error="crash", detail=detail)
        env = worker_env(os.environ, self.name, req.role, allow_api_key=req.allow_api_key)
        try:
            proc = run_process(
                self.command(req), cwd=req.cwd, env=env, timeout_s=req.timeout_s, log=req.log
            )
        except OSError as exc:
            return StepResult(session_id=req.session_id, error="crash", detail=str(exc))
        if proc.timed_out:
            return timed_out(req, proc)
        return self.parse(req, proc).model_copy(update={"duration_s": proc.duration_s})

    def detect(self) -> ProviderStatus:
        if shutil.which(self.binary) is None:
            return ProviderStatus(name=self.name, installed=False, hint=self.install_hint)
        result = probe([self.binary, "--version"])
        found = _VERSION.search(result.stdout) if result else None
        signed_in, method = self.signed_in()
        return ProviderStatus(
            name=self.name,
            installed=True,
            version=found.group(0) if found else None,
            signed_in=signed_in,
            auth_method=method,
            hint="" if signed_in else self.signin_hint,
            models=self.models() if signed_in else [],
        )
