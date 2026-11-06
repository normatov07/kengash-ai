"""Retry rules shared by ticket steps, plan reviews and compaction (SP3 spec §5 item 5)."""

from dataclasses import dataclass, field
from itertools import count
from pathlib import Path
from typing import Any

import pytest

from kengash_ai import adapters
from kengash_ai.model import StepRequest, StepResult, Usage, WorkOutput
from kengash_ai.ops import calls, prompts
from kengash_ai.store import StorePaths

OK = StepResult(
    session_id="s1",
    output=WorkOutput(summary="done", handoff="next"),
    usage=Usage(input=10, output=5),
)


@dataclass
class Scripted:
    """A provider that returns queued results and records every request."""

    results: list[StepResult]
    requests: list[StepRequest] = field(default_factory=list)

    def run(self, request: StepRequest) -> StepResult:
        self.requests.append(request)
        return self.results.pop(0)


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> Any:
    def install(*results: StepResult) -> Scripted:
        provider = Scripted(list(results))
        monkeypatch.setattr(adapters, "get", lambda name, runtime=None: provider)
        return provider

    return install


@pytest.fixture
def request_(tmp_path: Path) -> StepRequest:
    return StepRequest(
        role="planner",
        cwd=tmp_path,
        prompt="Plan it.",
        output="work",
        profile="read_only",
        timeout_s=60,
        log=tmp_path / "x-1.out",
        session_id="new-1",
        skill="be brief",
    )


def logs(tmp_path: Path) -> Any:
    numbers = count(2)
    return lambda: tmp_path / f"x-{next(numbers)}.out"


def test_a_timeout_retries_once_on_a_fresh_log(
    scripted: Any, request_: StepRequest, tmp_path: Path, store_paths: StorePaths
) -> None:
    timeout = StepResult(error="timeout", usage=Usage(input=3))
    provider = scripted(timeout, OK)
    called = calls.call(store_paths, "claude", request_, logs(tmp_path))
    assert called.result.ok and len(provider.requests) == 2
    assert provider.requests[1].log == tmp_path / "x-2.out"
    assert called.usage.input == 13 and called.request is provider.requests[1]


def test_a_second_timeout_is_returned(
    scripted: Any, request_: StepRequest, tmp_path: Path, store_paths: StorePaths
) -> None:
    provider = scripted(StepResult(error="timeout"), StepResult(error="timeout"))
    called = calls.call(store_paths, "claude", request_, logs(tmp_path))
    assert called.result.error == "timeout" and len(provider.requests) == 2


def test_a_schema_error_gets_one_repair_turn_on_the_session(
    scripted: Any, request_: StepRequest, tmp_path: Path, store_paths: StorePaths
) -> None:
    schema = StepResult(session_id="s1", error="schema", detail="missing handoff")
    provider = scripted(schema, OK)
    called = calls.call(store_paths, "claude", request_, logs(tmp_path))
    repair = provider.requests[1]
    assert called.result.ok
    assert (repair.resume, repair.session_id, repair.skill) == (True, "s1", None)
    assert repair.prompt.startswith("Your last reply failed: missing handoff")


def test_other_errors_return_at_once(
    scripted: Any, request_: StepRequest, tmp_path: Path, store_paths: StorePaths
) -> None:
    provider = scripted(StepResult(error="auth", detail="401"))
    called = calls.call(store_paths, "claude", request_, logs(tmp_path))
    assert called.result.error == "auth" and len(provider.requests) == 1
    assert calls.failure("claude", called.request, called.result) == (
        "sign in to claude interactively"
    )


def test_an_empty_turn_with_denied_actions_gets_one_repair_turn(
    scripted: Any, request_: StepRequest, tmp_path: Path, store_paths: StorePaths
) -> None:
    denied = StepResult(session_id="c-1", error="empty", detail="no output; denied: RunCommand")
    provider = scripted(denied, OK)
    called = calls.call(store_paths, "antigravity", request_, logs(tmp_path))
    repair = provider.requests[1]
    assert called.result.ok and (repair.resume, repair.session_id) == (True, "c-1")
    assert "RunCommand" in repair.prompt and "file tools" in repair.prompt


def test_an_empty_turn_without_denials_returns_at_once(
    scripted: Any, request_: StepRequest, tmp_path: Path, store_paths: StorePaths
) -> None:
    provider = scripted(StepResult(error="empty", detail="no output"))
    assert calls.call(store_paths, "claude", request_, logs(tmp_path)).result.error == "empty"
    assert len(provider.requests) == 1


def test_a_network_error_resumes_once_with_the_network_prompt(
    scripted: Any, request_: StepRequest, tmp_path: Path, store_paths: StorePaths
) -> None:
    cut = StepResult(session_id="s1", error="network", detail="connection reset by peer")
    provider = scripted(cut, OK)
    called = calls.call(store_paths, "claude", request_, logs(tmp_path))
    resumed = provider.requests[1]
    assert called.result.ok
    assert (resumed.resume, resumed.session_id, resumed.prompt) == (
        True,
        "s1",
        prompts.NETWORK_PROMPT,
    )


def test_a_second_network_error_is_returned(
    scripted: Any, request_: StepRequest, tmp_path: Path, store_paths: StorePaths
) -> None:
    cut = StepResult(session_id="s1", error="network", detail="connection reset by peer")
    provider = scripted(cut, cut)
    called = calls.call(store_paths, "claude", request_, logs(tmp_path))
    assert called.result.error == "network" and len(provider.requests) == 2


def test_failure_line_is_short_and_names_the_worktree(
    request_: StepRequest, tmp_path: Path
) -> None:
    detail = '{"handoff": "' + "x" * 2000 + '"}\nsecond line'
    result = StepResult(error="crash", detail=detail)
    line = calls.failure("antigravity", request_, result, worktree=tmp_path / "kg-1", changed=3)
    assert len(line) <= 300 and line.startswith('crash: {"handoff": "xxx')
    assert line.endswith(
        f"; log: {request_.log}; work kept in {tmp_path / 'kg-1'} (3 files changed)"
    )
    assert "second line" not in line
    plain = calls.failure("codex", request_, StepResult(error="crash", detail="boom"))
    assert plain == f"crash: boom; log: {request_.log}"


def test_a_fresh_session_cut_before_it_began_is_run_again_not_resumed(
    scripted: Any, request_: StepRequest, tmp_path: Path, store_paths: StorePaths
) -> None:
    fresh = request_.model_copy(update={"session_id": "u-1", "resume": False})
    cut = StepResult(error="network", detail="connect ECONNREFUSED")
    provider = scripted(cut, OK)
    calls.call(store_paths, "claude", fresh, logs(tmp_path))
    again = provider.requests[1]
    assert (again.resume, again.session_id, again.prompt) == (False, "u-1", fresh.prompt)
