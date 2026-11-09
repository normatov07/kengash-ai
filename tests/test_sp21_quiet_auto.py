"""Auto mode asks only about the loop limit (SP21 spec)."""

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import test_workflow

from kengash_ai import settings, workflow
from kengash_ai.model import Doc, Settings, Ticket, utc_now
from kengash_ai.ops import controls, merging, queue, relay
from kengash_ai.store import StorePaths, documents, runtime

Make = Callable[..., Doc[Ticket]]
SLUG = "payments-api"


def rules(mode: str = "auto") -> Settings:
    return test_workflow.settings(loop_start=mode, plan={"review_max": 2})


def progress(**fields: Any) -> workflow.Progress:
    base: dict[str, Any] = {
        "workflow": "standard",
        "hitl": False,
        "step": "review_code",
        "loop": 1,
        "loop_max": 4,
        "tokens": 0,
        "tokens_max": 1000,
        "streaks": {},
        "plan_rounds": 0,
    }
    return workflow.Progress(**(base | fields))


def test_auto_mode_grants_tokens_without_asking() -> None:
    routed = workflow.before(rules(), progress(tokens=5000))
    assert isinstance(routed.decision, workflow.Run)
    assert routed.progress.tokens_max == 5000 + rules().tokens.per_ticket_max


def test_ask_mode_still_stops_at_the_token_cap() -> None:
    routed = workflow.before(rules("ask"), progress(tokens=5000))
    assert isinstance(routed.decision, workflow.Halt)
    assert routed.decision.approval == "token_cap"


def fail_plan_review(mode: str) -> workflow.Routed:
    return workflow.after(
        rules(mode), progress(step="review_plan", plan_rounds=1), workflow.Outcome("fail", ("x",))
    )


def test_a_stalled_plan_review_becomes_the_loop_question() -> None:
    routed = fail_plan_review("auto")
    decision = routed.decision
    assert isinstance(decision, workflow.Halt)
    assert (decision.status, decision.approval) == (workflow.NEEDS_APPROVAL, "loop_cap")
    assert decision.reason.startswith("loop cap: plan review failed")
    assert (routed.progress.step, routed.progress.plan_rounds) == ("plan", 0)


def test_ask_mode_still_stalls() -> None:
    assert fail_plan_review("ask").decision == workflow.Halt(
        workflow.STALLED, "plan review failed 2 rounds (plan.review_max: 2)"
    )


def test_a_raised_limit_tries_again_from_the_on_fail_step() -> None:
    routed = fail_plan_review("auto")
    again = workflow.approve(rules(), routed.progress, "loop_cap", loops=None, tokens=None)
    assert isinstance(again.decision, workflow.Run) and again.decision.step == "plan"
    assert again.progress.loop == 2


def test_a_repeated_finding_becomes_the_loop_question() -> None:
    seen = {"review_code": {"abc": 1}}
    routed = workflow.after(rules(), progress(streaks=seen), workflow.Outcome("fail", ("abc",)))
    assert isinstance(routed.decision, workflow.Halt)
    assert routed.decision.approval == "loop_cap"
    assert routed.progress.step == "implement"
    assert routed.progress.streaks["review_code"] == {}


def stale(make: Make, **fields: Any) -> Doc[Ticket]:
    return make(updated=utc_now() - timedelta(minutes=30), **fields)


@pytest.fixture
def auto_project(store_paths: StorePaths, inside_registered_repo: Path) -> StorePaths:
    settings.set_values(store_paths, SLUG, {"loop_start": "auto"})
    return store_paths


def save(paths: StorePaths, doc: Doc[Ticket]) -> None:
    documents.save_ticket(paths.project(SLUG), doc)


def test_auto_mode_retries_a_failed_ticket_twice(
    auto_project: StorePaths, make_ticket: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    save(auto_project, stale(make_ticket, status="in_process/failed", step="implement"))
    runs: list[list[str]] = []
    monkeypatch.setattr(controls, "run_tickets", lambda ids, **k: runs.append(list(ids)))
    for _ in range(3):
        relay._recover(auto_project, SLUG)
    assert runs == [["7b55e0c1"], ["7b55e0c1"]]
    assert runtime.load_ticket_state(auto_project, "7b55e0c1").auto_retries == 2


def test_a_fresh_failure_waits(
    auto_project: StorePaths, make_ticket: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    save(auto_project, make_ticket(status="in_process/failed", step="implement", updated=utc_now()))
    monkeypatch.setattr(controls, "run_tickets", lambda ids, **k: pytest.fail("restarted"))
    relay._recover(auto_project, SLUG)


def test_ask_mode_never_retries(
    store_paths: StorePaths,
    inside_registered_repo: Path,
    make_ticket: Make,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save(store_paths, stale(make_ticket, status="in_process/failed", step="implement"))
    monkeypatch.setattr(controls, "run_tickets", lambda ids, **k: pytest.fail("restarted"))
    relay._recover(store_paths, SLUG)


def test_auto_mode_retries_a_merge(
    auto_project: StorePaths, make_ticket: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    save(auto_project, stale(make_ticket, status="in_process/awaiting_merge", step=None))
    merges: list[str] = []

    def merge(paths: StorePaths, slug: str, ticket: str, *, by: str) -> str:
        merges.append(ticket)
        return "done/merged"

    monkeypatch.setattr(merging, "merge_if_clean", merge)
    relay._recover(auto_project, SLUG)
    assert merges == ["7b55e0c1"]


def test_a_gate_leaves_independent_tickets_runnable(
    store_paths: StorePaths, inside_registered_repo: Path, make_ticket: Make
) -> None:
    gated = make_ticket(status="in_process/needs_approval", step="implement", touches=["a/x.py"])
    behind = make_ticket(
        "a0000001", status="in_queue/blocked", depends_on=["7b55e0c1"], touches=["b/y.py"]
    )
    free = make_ticket("a0000002", touches=["a/x.py"])
    for doc in (gated, behind, free):
        save(store_paths, doc)
    found = queue.compute(store_paths, SLUG)
    assert [item.id for item in found.runnable] == ["a0000002"]
    assert found.blocked == 1
