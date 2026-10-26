"""Adapter core: process runner, worker environment, shell provider, registry (SP3 spec §8)."""

import os
import signal
import time
from pathlib import Path
from typing import Any

import pytest

from super_harness.adapters import get
from super_harness.adapters.base import classify, positional
from super_harness.adapters.env import worker_env
from super_harness.adapters.process import run_process
from super_harness.adapters.shell import Shell
from super_harness.model import NeedsSetup, ReviewOutput, StepRequest, UserError


def _request(tmp_path: Path, **fields: Any) -> StepRequest:
    base = {
        "role": "test-runner",
        "cwd": tmp_path,
        "prompt": "",
        "output": "review",
        "profile": "read_only",
        "timeout_s": 5,
        "log": tmp_path / "logs" / "t-1.out",
    }
    return StepRequest.model_validate(base | fields)


def test_run_process_writes_the_log_and_returns_output(tmp_path: Path) -> None:
    log = tmp_path / "logs" / "a-1.out"
    result = run_process(
        ["sh", "-c", "echo out; echo err >&2; exit 3"],
        cwd=tmp_path,
        env=dict(os.environ),
        timeout_s=5,
        log=log,
    )
    assert (result.exit_code, result.stdout, result.stderr, result.timed_out) == (
        3,
        "out\n",
        "err\n",
        False,
    )
    assert log.read_text() == "out\n" and log.with_suffix(".err").read_text() == "err\n"


def _gone(pid: int, within: float = 3.0) -> bool:
    """True once `pid` no longer exists; polls, because a killed child may linger as a zombie."""
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def test_a_timeout_kills_the_whole_group_even_when_sigterm_is_ignored(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    script = f"trap '' TERM; sleep 30 & echo $! > {pid_file}; wait"
    started = time.monotonic()
    result = run_process(
        ["sh", "-c", script],
        cwd=tmp_path,
        env=dict(os.environ),
        timeout_s=1,
        log=tmp_path / "t.out",
        grace_s=1,
    )
    assert result.timed_out and time.monotonic() - started < 6
    assert _gone(int(pid_file.read_text()))


def test_background_children_die_when_the_cli_exits(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    run_process(
        ["sh", "-c", f"sleep 30 & echo $! > {pid_file}"],
        cwd=tmp_path,
        env=dict(os.environ),
        timeout_s=5,
        log=tmp_path / "b.out",
    )
    assert _gone(int(pid_file.read_text()))


def test_worker_env_drops_keys_and_conductor_markers() -> None:
    environ = {
        "PATH": "/bin",
        "ANTHROPIC_API_KEY": "a",
        "OPENAI_API_KEY": "o",
        "CODEX_API_KEY": "c",
        "GEMINI_API_KEY": "g",
        "GOOGLE_API_KEY": "k",
        "CLAUDECODE": "1",
        "CLAUDE_CODE_ENTRYPOINT": "cli",
    }
    assert worker_env(environ, "claude", "planner", allow_api_key=False) == {
        "PATH": "/bin",
        "HARNESS_AGENT": "planner",
    }
    kept = worker_env(environ, "codex", "implementer", allow_api_key=True)
    assert {k for k in kept if k.endswith("_API_KEY")} == {"OPENAI_API_KEY", "CODEX_API_KEY"}


def test_positional_prompts_never_look_like_flags() -> None:
    assert positional("---\nname: plan") == "\n---\nname: plan"
    assert positional("You are the planner") == "You are the planner"


def test_classify_reads_auth_and_rate_limit_text() -> None:
    assert classify("Invalid API key · Please run /login") == "auth"
    assert classify("Not logged in") == "auth"
    assert classify("You've hit your usage limit. Try again in 2 hours") == "rate_limit"
    assert classify("RESOURCE_EXHAUSTED: quota") == "rate_limit"
    assert classify("segfault") == "crash"


def test_shell_passes_on_exit_zero(tmp_path: Path) -> None:
    result = Shell().run(_request(tmp_path, test_cmd="echo ok"))
    assert result.ok and result.output == ReviewOutput(
        verdict="pass", summary="tests passed", findings=[]
    )


def test_shell_failure_keeps_the_last_20_lines_even_when_not_utf8(tmp_path: Path) -> None:
    script = "for i in $(seq 1 30); do echo line$i; done; printf '\\377\\376 bad'; exit 2"
    result = Shell().run(_request(tmp_path, test_cmd=script))
    assert isinstance(result.output, ReviewOutput) and result.output.verdict == "fail"
    assert result.output.summary == "tests failed (exit 2)"
    [finding] = result.output.findings
    assert finding.issue.splitlines()[0] == "line12" and "�" in finding.issue
    assert (finding.severity, finding.file, finding.line, finding.fix) == (
        "high",
        "",
        0,
        "make project.test_cmd pass",
    )


def test_shell_without_a_test_command_fails(tmp_path: Path) -> None:
    result = Shell().run(_request(tmp_path))
    assert (result.error, result.detail) == ("crash", "set project.test_cmd")


def test_shell_timeout(tmp_path: Path) -> None:
    result = Shell().run(_request(tmp_path, test_cmd="sleep 10", timeout_s=1))
    assert (result.error, result.detail) == ("timeout", "killed after 1 s")


def test_get_knows_the_providers(tmp_path: Path) -> None:
    assert get("shell", runtime=tmp_path).name == "shell"
    with pytest.raises(NeedsSetup, match="gemini is not supported"):
        get("gemini", runtime=tmp_path)
    with pytest.raises(UserError, match="unknown provider: cursor"):
        get("cursor", runtime=tmp_path)


def test_an_interrupted_wait_ends_the_cli_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_file = tmp_path / "cli.pid"

    def interrupt(signum: int, frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGALRM, interrupt)
    signal.alarm(1)
    with pytest.raises(KeyboardInterrupt):
        run_process(
            ["sh", "-c", f"echo $$ > {pid_file}; sleep 30"],
            cwd=tmp_path,
            env=dict(os.environ),
            timeout_s=30,
            log=tmp_path / "i.out",
        )
    assert _gone(int(pid_file.read_text()))


def test_gemini_points_to_antigravity(tmp_path: Path) -> None:
    with pytest.raises(NeedsSetup) as found:
        get("gemini", runtime=tmp_path)
    assert "Antigravity CLI" in str(found.value) and "pick antigravity" in str(found.value)
