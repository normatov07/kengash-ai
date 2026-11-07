"""Adapter core: process runner, worker environment, shell provider, registry (SP3 spec §8)."""

import os
import shutil
import signal
import time
from pathlib import Path
from typing import Any

import pytest

from kengash_ai.adapters import get
from kengash_ai.adapters.base import classify, positional
from kengash_ai.adapters.env import worker_env
from kengash_ai.adapters.process import run_process
from kengash_ai.adapters.shell import Shell
from kengash_ai.model import ReviewOutput, StepRequest, UserError


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
        "KENGASH_AGENT": "planner",
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


def test_shell_failure_digests_the_output_even_when_not_utf8(tmp_path: Path) -> None:
    script = "for i in $(seq 1 30); do echo line$i; done; printf 'error: \\377\\376 bad'; exit 2"
    result = Shell().run(_request(tmp_path, test_cmd=script))
    assert isinstance(result.output, ReviewOutput) and result.output.verdict == "fail"
    assert result.output.summary == "tests failed (exit 2)"
    [finding] = result.output.findings
    assert finding.issue.startswith(f"`{script}` exit 2: error: ") and "\ufffd" in finding.issue
    assert (finding.severity, finding.file, finding.line) == ("high", "", 0)
    assert finding.fix == f"fix the cause in Check output, then run {script}"
    assert result.check_output.startswith(finding.issue + "\n```text\n")
    assert "line30" in result.check_output and "line10" not in result.check_output


def test_a_lint_failure_names_the_lint_command(tmp_path: Path) -> None:
    lint = "echo 'warning: x' && exit 2"
    result = Shell().run(_request(tmp_path, test_cmd="true", lint_cmd=lint))
    assert isinstance(result.output, ReviewOutput)
    assert result.output.summary == "lint failed (exit 2)"
    [finding] = result.output.findings
    assert finding.issue == f"`{lint}` exit 2: warning: x"
    assert finding.fix == f"fix the cause in Check output, then run {lint}"


def test_a_pass_has_no_check_output(tmp_path: Path) -> None:
    result = Shell().run(_request(tmp_path, test_cmd="echo ok", lint_cmd="true"))
    assert result.check_output == ""


def test_shell_without_a_test_command_fails(tmp_path: Path) -> None:
    result = Shell().run(_request(tmp_path))
    assert (result.error, result.detail) == ("crash", "set project.test_cmd")


def test_shell_timeout(tmp_path: Path) -> None:
    result = Shell().run(_request(tmp_path, test_cmd="sleep 10", timeout_s=1))
    assert (result.error, result.detail) == ("timeout", "killed after 1 s")


def test_get_knows_the_providers(tmp_path: Path) -> None:
    assert get("shell", runtime=tmp_path).name == "shell"
    with pytest.raises(UserError, match="gemini is replaced by antigravity"):
        get("gemini", runtime=tmp_path)
    with pytest.raises(UserError, match="unknown provider: cursor"):
        get("cursor", runtime=tmp_path)


def test_an_interrupted_wait_ends_the_cli_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_file = tmp_path / "cli.pid"

    def interrupt(signum: int, frame: object) -> None:
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGALRM, interrupt)
    signal.alarm(1)
    try:
        with pytest.raises(KeyboardInterrupt):
            run_process(
                ["sh", "-c", f"echo $$ > {pid_file}; sleep 30"],
                cwd=tmp_path,
                env=dict(os.environ),
                timeout_s=30,
                log=tmp_path / "i.out",
            )
    finally:  # no later test may meet this handler or a pending alarm
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    assert _gone(int(pid_file.read_text()))


@pytest.mark.parametrize(
    "message",
    [
        'request failed: Post "https://x/v1": read tcp 10.0.0.1:47416->172.217.115.4:443: '
        "read: connection reset by peer",
        "dial tcp: lookup api.example.com: no such host",
        "stream error: stream ID 7; INTERNAL_ERROR",
        "upstream returned 503 Service Unavailable",
        "rpc error: code = UNAVAILABLE desc = overloaded",
        "write: broken pipe",
    ],
)
def test_classify_network(message: str) -> None:
    assert classify(message) == "network"


def test_auth_and_rate_limit_win_over_network() -> None:
    assert classify("429 Too Many Requests; connection reset by peer") == "rate_limit"
    assert classify("401 unauthorized after EOF") == "auth"
    assert classify("the tests failed") == "crash"


def test_step_results_carry_a_warning() -> None:
    from kengash_ai.model import StepResult

    assert StepResult(warning="connection reset").warning == "connection reset"


def test_stdout_lines_get_stamps(tmp_path: Path) -> None:
    from datetime import datetime

    log = tmp_path / "logs" / "t-1.out"
    result = run_process(
        ["sh", "-c", "echo a; sleep 0.3; echo b"],
        cwd=tmp_path,
        env=dict(os.environ),
        timeout_s=10,
        log=log,
    )
    assert result.stdout == "a\nb\n" and log.read_text() == "a\nb\n"
    stamps = [datetime.fromisoformat(line) for line in log.with_suffix(".ts").read_text().split()]
    assert len(stamps) == 2 and (stamps[1] - stamps[0]).total_seconds() >= 0.25


def test_lint_runs_after_tests(tmp_path: Path) -> None:
    result = Shell().run(_request(tmp_path, test_cmd="echo t", lint_cmd="echo l"))
    assert isinstance(result.output, ReviewOutput) and result.output.verdict == "pass"
    assert result.output.summary == "tests and lint passed"


def test_lint_failure_fails_the_step(tmp_path: Path) -> None:
    result = Shell().run(_request(tmp_path, test_cmd="echo t", lint_cmd="echo bad; exit 3"))
    assert isinstance(result.output, ReviewOutput) and result.output.verdict == "fail"
    assert result.output.summary == "lint failed (exit 3)"
    (finding,) = result.output.findings
    assert "bad" in finding.issue
    assert finding.fix == "fix the cause in Check output, then run echo bad; exit 3"


def test_failing_tests_skip_lint(tmp_path: Path) -> None:
    marker = tmp_path / "linted"
    result = Shell().run(_request(tmp_path, test_cmd="exit 1", lint_cmd=f"touch {marker}"))
    assert (
        isinstance(result.output, ReviewOutput) and result.output.summary == "tests failed (exit 1)"
    )
    assert not marker.exists()


def test_only_lint_set(tmp_path: Path) -> None:
    result = Shell().run(_request(tmp_path, lint_cmd="echo l"))
    assert isinstance(result.output, ReviewOutput) and result.output.summary == "lint passed"


@pytest.mark.parametrize(
    "message",
    [
        "API Error: Connection error.",
        "API Error: Request timed out.",
        "connect ECONNREFUSED 160.79.104.10:443",
        "getaddrinfo ENOTFOUND api.anthropic.com",
        "connect ETIMEDOUT 160.79.104.10:443",
        "TypeError: fetch failed",
        "socket hang up",
    ],
)
def test_classify_claude_network_wording(message: str) -> None:
    assert classify(message) == "network"


@pytest.mark.skipif(shutil.which("setsid") is None, reason="setsid is not installed")
def test_an_escaped_child_holding_stdout_does_not_hang_the_call(tmp_path: Path) -> None:
    started = time.monotonic()
    result = run_process(
        ["sh", "-c", "setsid sleep 8 & echo hi; sleep 30"],
        cwd=tmp_path,
        env=dict(os.environ),
        timeout_s=1,
        log=tmp_path / "logs" / "t-1.out",
        grace_s=1,
    )
    assert result.timed_out and time.monotonic() - started < 5


def test_the_pump_stamps_before_it_writes() -> None:
    from io import BytesIO

    from kengash_ai.adapters.process import _pump

    order: list[str] = []

    class Out:
        def write(self, data: object) -> None:
            order.append("stamp" if isinstance(data, str) else "line")

        def flush(self) -> None:
            pass

    _pump(BytesIO(b"a\nb\n"), Out(), Out())  # type: ignore[arg-type]
    assert order == ["stamp", "line", "stamp", "line"]
