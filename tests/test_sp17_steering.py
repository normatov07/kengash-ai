"""Steering: a stuck or timed-out call is corrected, not repeated (SP17 spec §3.1, §3.3)."""

from typing import Any

import pytest
from conftest import Engine, Events, write_settings

from kengash_ai import adapters
from kengash_ai.adapters.base import classify
from kengash_ai.model import PlanOutput, ProviderStatus, StepRequest, StepResult
from kengash_ai.ops import steps

PLAN = PlanOutput(summary="s", handoff="h")
FALLBACK = "agents:\n  planner: {cli: claude/opus, skill: plan, fallback: [antigravity]}\n"


class Scripted:
    def __init__(self, name: str, results: list[StepResult], seen: list[StepRequest]) -> None:
        self.name, self.results, self.seen = name, results, seen

    def detect(self) -> ProviderStatus:
        return ProviderStatus(name=self.name, installed=True, signed_in=True)

    def run(self, req: StepRequest) -> StepResult:
        self.seen.append(req)
        return self.results.pop(0)


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(steps, "CRASH_WAIT_S", 0)

    def install(claude: list[StepResult], agy: list[StepResult] | None = None) -> list[StepRequest]:
        seen: list[StepRequest] = []
        table = {
            "claude": Scripted("claude", claude, seen),
            "antigravity": Scripted("antigravity", agy or [], seen),
        }
        monkeypatch.setattr(adapters, "get", lambda name, runtime: table[name])
        return seen

    return install


def stuck(why: str = "you made 8 polls") -> StepResult:
    return StepResult(session_id="s-1", error="stuck", detail=why)


def done() -> StepResult:
    return StepResult(session_id="s-1", output=PLAN)


def test_a_stuck_call_resumes_with_a_correction(
    engine: Engine, script: Any, journal_events: Events
) -> None:
    seen = script([stuck(), done()])
    steps.run_job("7b55e0c1", steps=1)
    first, second = seen
    assert first.soft_s == 20 * 60 and first.poll_max == 8 and first.full_runs_max == 2
    assert second.resume and second.session_id == "s-1"
    assert "kengash stopped your turn: you made 8 polls" in second.prompt
    assert "do not run the whole test suite" in second.prompt
    assert second.soft_s == 10 * 60
    assert "steered" in engine.ticket().sections["Log"]
    assert any(e["type"] == "step.steered" for e in journal_events())


def test_corrections_run_out_then_the_ticket_fails(engine: Engine, script: Any) -> None:
    seen = script([stuck(), stuck(), stuck()])
    steps.run_job("7b55e0c1", steps=1)
    assert len(seen) == 3
    doc = engine.ticket()
    assert doc.meta.status == "in_process/failed"


def test_corrections_run_out_then_the_fallback_takes_over(engine: Engine, script: Any) -> None:
    write_settings(engine.paths, FALLBACK)
    seen = script([stuck(), stuck(), stuck()], [StepResult(session_id="a-1", output=PLAN)])
    steps.run_job("7b55e0c1", steps=1)
    assert len(seen) == 4
    assert not seen[3].resume
    assert engine.ticket().meta.status != "in_process/failed"


def test_a_stuck_call_with_no_session_cannot_be_corrected(engine: Engine, script: Any) -> None:
    seen = script([StepResult(error="stuck", detail="why")])
    steps.run_job("7b55e0c1", steps=1)
    assert len(seen) == 1


def test_a_timeout_resumes_with_a_correction(engine: Engine, script: Any) -> None:
    seen = script([StepResult(session_id="s-1", error="timeout", detail="killed"), done()])
    steps.run_job("7b55e0c1", steps=1)
    assert seen[1].resume
    assert "time limit" in seen[1].prompt


def test_a_second_timeout_goes_to_the_fallback(engine: Engine, script: Any) -> None:
    write_settings(engine.paths, FALLBACK)
    late = StepResult(session_id="s-1", error="timeout", detail="killed")
    seen = script([late, late.model_copy()], [StepResult(session_id="a-1", output=PLAN)])
    steps.run_job("7b55e0c1", steps=1)
    assert len(seen) == 3 and engine.ticket().meta.status != "in_process/failed"


def test_a_crash_is_retried_once(engine: Engine, script: Any) -> None:
    broken = StepResult(session_id="s-1", error="crash", detail="invalid model selection")
    seen = script([broken, done()])
    steps.run_job("7b55e0c1", steps=1)
    assert len(seen) == 2 and engine.ticket().meta.status != "in_process/failed"


def test_a_second_crash_fails_without_a_fallback(engine: Engine, script: Any) -> None:
    broken = StepResult(session_id="s-1", error="crash", detail="boom")
    seen = script([broken, broken.model_copy()])
    steps.run_job("7b55e0c1", steps=1)
    assert len(seen) == 2 and engine.ticket().meta.status == "in_process/failed"


@pytest.mark.parametrize(
    "text",
    [
        "API error (attempt 2): request failed: stream idle timeout (5m0s)",
        "context deadline exceeded",
    ],
)
def test_a_hung_stream_is_a_network_error(text: str) -> None:
    assert classify(text) == "network"
