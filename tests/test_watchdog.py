"""The watchdog inside a CLI call, and what a stopped call reports (SP17 spec §3.1, §3.3)."""

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from kengash_ai.adapters.antigravity import Antigravity
from kengash_ai.adapters.claude import Claude
from kengash_ai.adapters.codex import Codex
from kengash_ai.adapters.process import run_process
from kengash_ai.adapters.watchdog import Signal, Watchdog
from kengash_ai.model import StepRequest, Usage


def _agy(tool: str, state: str = "DONE", **params: Any) -> str:
    update = {"state": state, "step_type": "tool", "tool_name": tool}
    return json.dumps(
        {
            "event": "step_update",
            "step_update": update | {"tool_info": {"name": tool, "parameters": params}},
        }
    )


POLL = _agy("manage_task", Action="status", TaskId="t")
EDIT = _agy("edit_file", Path="a.dart")


def _dog(**fields: Any) -> Watchdog:
    options: dict[str, Any] = {
        "soft_s": 1200,
        "poll_max": 8,
        "full_runs_max": 2,
        "test_cmd": "flutter test",
    }
    return Watchdog(Antigravity().signal, **(options | fields))


def test_polling_with_no_edit_stops_the_call() -> None:
    dog = _dog()
    assert [dog.feed(POLL) for _ in range(7)] == [""] * 7
    assert "8 polls" in dog.feed(POLL)


def test_an_edit_resets_the_polls() -> None:
    dog = _dog()
    for _ in range(7):
        dog.feed(POLL)
    dog.feed(EDIT)
    assert dog.feed(POLL) == ""


def test_killing_a_background_task_is_no_poll() -> None:
    dog = _dog(poll_max=1)
    assert dog.feed(_agy("manage_task", Action="kill", TaskId="t")) == ""


def test_the_third_whole_suite_run_stops_the_call_as_it_starts() -> None:
    dog = _dog()
    run = _agy("run_command", state="ACTIVE", CommandLine="flutter test")
    assert dog.feed(run) == ""
    assert dog.feed(run) == ""
    assert "whole test suite" in dog.feed(run)


def test_a_targeted_test_is_not_a_whole_suite_run() -> None:
    dog = _dog(full_runs_max=1)
    run = _agy("run_command", state="ACTIVE", CommandLine="flutter test test/a_test.dart")
    assert [dog.feed(run) for _ in range(4)] == [""] * 4


def test_the_soft_deadline() -> None:
    dog = _dog(soft_s=60)
    assert dog.tick(59.0) == ""
    assert "1 minutes" in dog.tick(60.0)


def test_zero_turns_a_rule_off() -> None:
    dog = _dog(poll_max=0, full_runs_max=0)
    run = _agy("run_command", state="ACTIVE", CommandLine="flutter test")
    assert [dog.feed(line) for line in (POLL, POLL, run, run, run)] == [""] * 5


def test_a_line_that_is_not_json_is_ignored() -> None:
    assert _dog().feed("Resolving dependencies...") == ""


def test_claude_events() -> None:
    def tool(name: str, **given: Any) -> dict[str, Any]:
        block = {"type": "tool_use", "name": name, "input": given}
        return {"type": "assistant", "message": {"content": [block]}}

    claude = Claude()
    assert claude.signal(tool("Edit", file_path="a")) == Signal("edit")
    assert claude.signal(tool("BashOutput", bash_id="1")) == Signal("poll")
    assert claude.signal(tool("Bash", command="uv run pytest")) == Signal("run", "uv run pytest")
    assert claude.signal({"type": "system"}) is None


def test_codex_events(tmp_path: Path) -> None:
    codex = Codex(tmp_path)
    change = {"type": "item.completed", "item": {"type": "file_change"}}
    assert codex.signal(change) == Signal("edit")
    run = {"type": "item.started", "item": {"type": "command_execution", "command": "ls"}}
    assert codex.signal(run) == Signal("run", "ls")


def test_a_wrapped_command_counts_as_the_whole_suite(tmp_path: Path) -> None:
    dog = Watchdog(
        Codex(tmp_path).signal, soft_s=99, poll_max=0, full_runs_max=1, test_cmd="pytest -q"
    )
    line = json.dumps(
        {
            "type": "item.started",
            "item": {"type": "command_execution", "command": "bash -lc 'pytest -q'"},
        }
    )
    assert dog.feed(line) == ""
    assert dog.feed(line) != ""


class _Stop:
    def __init__(self, at: str) -> None:
        self.at = at

    def feed(self, line: str) -> str:
        return "stuck on it" if self.at in line else ""

    def tick(self, elapsed: float) -> str:
        return ""


def test_run_process_stops_when_the_observer_says(tmp_path: Path) -> None:
    result = run_process(
        ["sh", "-c", "echo first; echo halt; sleep 30; echo never"],
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin"},
        timeout_s=20,
        log=tmp_path / "x.out",
        grace_s=1,
        observe=_Stop("halt"),
    )
    assert result.stopped == "stuck on it"
    assert not result.timed_out
    assert result.duration_s < 10
    assert "never" not in result.stdout


def _fake(tmp_path: Path, name: str, body: str) -> None:
    path = tmp_path / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _request(tmp_path: Path, **fields: Any) -> StepRequest:
    base = {
        "role": "implementer",
        "cwd": tmp_path,
        "prompt": "do it",
        "output": "work",
        "profile": "edit_worktree",
        "timeout_s": 30,
        "log": tmp_path / "logs" / "a-1.out",
        "soft_s": 600,
        "poll_max": 1,
    }
    return StepRequest.model_validate(base | fields)


def _on_path(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")


def test_a_stopped_agy_call_keeps_its_session_and_tokens(tmp_path: Path, monkeypatch: Any) -> None:
    init = json.dumps({"event": "init", "conversation_id": "conv-1"})
    used = json.dumps(
        {
            "event": "step_update",
            "step_update": {
                "state": "DONE",
                "step_type": "agent_response",
                "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_tokens": 5},
            },
        }
    )
    _fake(tmp_path, "agy", f"echo '{init}'\necho '{used}'\necho '{POLL}'\nsleep 30\n")
    _on_path(monkeypatch, tmp_path)
    result = Antigravity().run(_request(tmp_path))
    assert result.error == "stuck"
    assert result.session_id == "conv-1"
    assert result.usage == Usage(input=100, output=20, cache_read=5)
    assert "1 polls" in result.detail


def test_a_valid_output_wins_over_the_stop(tmp_path: Path, monkeypatch: Any) -> None:
    payload = {
        "event": "result",
        "result": {
            "conversation_id": "conv-2",
            "status": "SUCCESS",
            "response": '{"summary": "s", "handoff": "h", "decisions": []}',
            "structured_output": {"summary": "s", "handoff": "h", "decisions": []},
            "usage": {"input_tokens": 3, "output_tokens": 4},
        },
    }
    _fake(tmp_path, "agy", f"echo '{json.dumps(payload)}'\necho '{POLL}'\nsleep 30\n")
    _on_path(monkeypatch, tmp_path)
    result = Antigravity().run(_request(tmp_path))
    assert result.error is None
    assert result.output is not None


def test_a_timed_out_claude_call_sums_what_it_used(tmp_path: Path, monkeypatch: Any) -> None:
    def said(ident: str, output: int) -> str:
        usage = {"input_tokens": 10, "output_tokens": output}
        message = {"id": ident, "content": [{"type": "text", "text": "hm"}], "usage": usage}
        return json.dumps({"type": "assistant", "message": message})

    init = json.dumps({"type": "system", "subtype": "init", "session_id": "s-1"})
    lines = "\n".join(
        f"echo '{line}'" for line in (init, said("m1", 1), said("m1", 7), said("m2", 2))
    )
    _fake(tmp_path, "claude", f"{lines}\nsleep 30\n")
    _on_path(monkeypatch, tmp_path)
    request = _request(tmp_path, timeout_s=1, soft_s=None, poll_max=0, session_id="s-1")
    result = Claude().run(request)
    assert result.error == "timeout"
    assert result.session_id == "s-1"
    assert result.usage.output == 9
    assert result.usage.input == 20


class _BrokenObserver:
    def feed(self, line: str) -> str:
        raise AttributeError("an event of a shape no driver expected")

    def tick(self, elapsed: float) -> str:
        return ""


def test_a_broken_watchdog_never_costs_the_call(tmp_path: Path) -> None:
    result = run_process(
        ["bash", "-c", "yes line | head -n 40000"],  # more than a pipe holds
        cwd=tmp_path,
        env=dict(os.environ),
        timeout_s=5,
        log=tmp_path / "call.out",
        grace_s=1,
        observe=_BrokenObserver(),
    )
    assert not result.timed_out
    assert result.stdout.count("line\n") == 40000


def test_a_suite_run_piped_to_tail_still_counts() -> None:
    dog = Watchdog(lambda event: None, soft_s=99, poll_max=0, full_runs_max=1, test_cmd="pytest -q")
    assert dog._count(Signal("run", "pytest -q 2>&1 | tail -20")) == ""
    assert "2 times" in dog._count(Signal("run", "bash -lc 'cd app && pytest -q > out.txt'"))


def test_one_test_file_piped_to_tail_does_not_count() -> None:
    dog = Watchdog(lambda event: None, soft_s=99, poll_max=0, full_runs_max=1, test_cmd="pytest -q")
    for _ in range(3):
        assert dog._count(Signal("run", "pytest -q tests/test_a.py 2>&1 | tail -20")) == ""


def test_a_stopped_call_carries_the_running_total(tmp_path: Path, monkeypatch: Any) -> None:
    init = json.dumps({"event": "init", "conversation_id": "conv-1"})
    used = json.dumps(
        {
            "event": "step_update",
            "step_update": {
                "state": "DONE",
                "step_type": "agent_response",
                "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_tokens": 5},
            },
        }
    )
    _fake(tmp_path, "agy", f"echo '{init}'\necho '{used}'\necho '{POLL}'\nsleep 30\n")
    _on_path(monkeypatch, tmp_path)
    prior = Usage(input=1000, output=200, cache_read=50)
    request = _request(tmp_path, resume=True, session_id="conv-1", prior_usage=prior)
    result = Antigravity().run(request)
    assert result.error == "stuck"
    assert result.usage == Usage(input=100, output=20, cache_read=5)
    assert result.total_usage == Usage(input=1100, output=220, cache_read=55)


@pytest.mark.parametrize(
    "command",
    ['bash -lc "pytest -q"', "pytest -q; echo $?", "pytest -q && ruff check ."],
)
def test_a_suite_run_inside_a_longer_line_counts(command: str) -> None:
    dog = Watchdog(lambda event: None, soft_s=99, poll_max=0, full_runs_max=1, test_cmd="pytest -q")
    assert dog._count(Signal("run", command)) == ""
    assert "2 times" in dog._count(Signal("run", command))


def test_one_test_file_in_a_longer_line_does_not_count() -> None:
    dog = Watchdog(lambda event: None, soft_s=99, poll_max=0, full_runs_max=1, test_cmd="pytest -q")
    for _ in range(3):
        assert dog._count(Signal("run", "cd app && pytest -q tests/a.py; echo $?")) == ""
