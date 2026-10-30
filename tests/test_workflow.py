from typing import Any

import pytest

from kengash_ai.model import Settings
from kengash_ai.workflow import (
    AWAITING_MERGE,
    BRANCH_READY,
    FAILED,
    NEEDS_APPROVAL,
    PARKED,
    STALLED,
    Halt,
    Merge,
    Outcome,
    Progress,
    Run,
    after,
    approve,
    before,
    fingerprint,
    first_step,
    steps_for,
)

AGENTS: dict[str, Any] = {
    "planner": {"cli": "claude/opus", "skill": "plan"},
    "plan-reviewer": {"cli": "codex", "skill": "review-plan"},
    "implementer": {"cli": "codex", "skill": "implement"},
    "code-reviewer": {"cli": "claude/opus", "skill": "review-code"},
    "security-reviewer": {"cli": "claude/sonnet", "skill": "review-security", "blocking": True},
}
WORKFLOWS: dict[str, Any] = {
    "standard": {
        "steps": ["plan", "review_plan", "implement", "review_code"],
        "on_fail": {"review_plan": "plan", "review_code": "implement"},
    },
    "critical": {
        "steps": ["plan", "review_plan", "implement", "review_code", "security"],
        "on_fail": {"review_plan": "plan", "review_code": "implement", "security": "implement"},
    },
    "bare": {"steps": ["implement", "review_code"]},
}
PASS = Outcome("pass")
DONE = Halt(AWAITING_MERGE, "every step passed")


def settings(agents: dict[str, Any] | None = None, **fields: Any) -> Settings:
    data = {"agents": AGENTS | (agents or {}), "workflows": WORKFLOWS} | fields
    return Settings.model_validate(data)


def off(role: str) -> dict[str, Any]:
    return {role: AGENTS[role] | {"on": False}}


def progress(step: str | None = "review_code", **fields: Any) -> Progress:
    base: dict[str, Any] = {
        "workflow": "standard",
        "hitl": False,
        "step": step,
        "loop": 1,
        "loop_max": 4,
        "tokens": 0,
        "tokens_max": 250_000,
    }
    return Progress(**(base | fields))


def fail(*fingerprints: str) -> Outcome:
    return Outcome("fail", fingerprints)


def test_effective_steps_skip_off_roles_and_add_approval() -> None:
    full = ["plan", "review_plan", "implement", "review_code"]
    assert steps_for(settings(), "standard", hitl=False) == full
    assert steps_for(settings(off("code-reviewer")), "standard", hitl=False) == full[:3]
    no_review = settings(plan={"review_max": 0})
    assert steps_for(no_review, "standard", hitl=False) == ["plan", "implement", "review_code"]
    assert steps_for(settings(), "standard", hitl=True) == ["plan", "approve", *full[1:]]
    assert steps_for(settings(), "bare", hitl=True) == ["approve", "implement", "review_code"]


def test_before_runs_the_step_or_halts_at_a_gate() -> None:
    assert before(settings(), progress()).decision == Run("review_code", 1)
    capped = before(settings(), progress(tokens=250_000)).decision
    assert capped == Halt(NEEDS_APPROVAL, "token cap: 250000 of 250000", "token_cap")
    gate = before(settings(), progress("approve", hitl=True)).decision
    assert gate == Halt(NEEDS_APPROVAL, "waiting for the user's approval", "approve_step")


def test_a_blocking_role_that_is_off_fails_the_ticket() -> None:
    routed = before(settings(off("security-reviewer")), progress(workflow="critical"))
    assert routed.decision == Halt(FAILED, "role security-reviewer is off and blocking")


def test_a_step_whose_role_was_switched_off_is_skipped() -> None:
    routed = before(settings(off("plan-reviewer")), progress("review_plan"))
    assert (routed.decision, routed.progress.step) == (Run("implement", 1), "implement")
    assert before(settings(off("code-reviewer")), progress()).decision == DONE
    unknown = before(settings(), progress("docs"))
    assert unknown.decision == Halt(FAILED, "workflow standard has no step docs")


def test_a_pass_moves_on_and_the_last_pass_follows_merge_mode() -> None:
    assert after(settings(), progress("implement"), PASS).decision == Run("review_code", 1)
    assert after(settings(), progress(), PASS).decision == DONE
    assert after(settings(merge={"mode": "auto"}), progress(), PASS).decision == Merge()
    branch = after(settings(merge={"mode": "branch"}), progress(), PASS)
    waiting = "every step passed; the branch waits for the user"
    assert (branch.decision, branch.progress.step) == (Halt(BRANCH_READY, waiting), None)
    hitl = progress(hitl=True)
    assert after(settings(merge={"mode": "auto"}), hitl, PASS).decision == DONE


def test_a_failing_review_recirculates_with_one_more_loop() -> None:
    routed = after(settings(), progress(), fail("a1"))
    assert routed.decision == Run("implement", 2)
    assert (routed.progress.step, routed.progress.loop) == ("implement", 2)
    assert routed.progress.streaks == {"review_code": {"a1": 1}}


def test_a_failure_at_the_loop_cap_asks_the_user_or_parks() -> None:
    routed = after(settings(), progress(loop=4), fail("a1"))
    assert routed.decision == Halt(NEEDS_APPROVAL, "loop cap: 4 of 4", "loop_cap")
    assert (routed.progress.step, routed.progress.loop) == ("implement", 4)
    parked = after(settings(loop_ask_at_cap=False), progress(loop=4), fail("a1"))
    assert parked.decision == Halt(PARKED, "loop cap: 4 of 4")


def test_the_same_finding_failing_twice_in_a_row_stalls() -> None:
    seen = progress(streaks={"review_code": {"a1": 1}})
    stalled = after(settings(), seen, fail("a1", "b2"))
    assert stalled.decision == Halt(STALLED, "same finding failed 2 loops in a row: a1")
    moved_on = after(settings(), seen, fail("b2"))
    assert moved_on.decision == Run("implement", 2)
    assert moved_on.progress.streaks == {"review_code": {"b2": 1}}
    assert after(settings(), seen, PASS).progress.streaks == {"review_code": {}}


def test_plan_review_rounds_are_capped_by_plan_review_max() -> None:
    first = after(settings(), progress("review_plan"), fail("p1"))
    assert (first.decision, first.progress.plan_rounds) == (Run("plan", 2), 1)
    second = after(settings(), progress("review_plan", loop=2, plan_rounds=1), fail("p2"))
    assert second.decision == Halt(STALLED, "plan review failed 2 rounds (plan.review_max: 2)")


def test_plan_review_failures_can_leave_the_loop_count_alone() -> None:
    lenient = settings(loop_count_rejected_review=False)
    assert after(lenient, progress("review_plan", loop=4), fail("p1")).decision == Run("plan", 4)


def test_a_failure_without_an_on_fail_edge_fails_the_ticket() -> None:
    routed = after(settings(), progress(workflow="bare"), fail("a1"))
    assert routed.decision == Halt(FAILED, "review_code failed and has no on_fail step")


def test_approvals_grant_loops_tokens_or_pass_the_approval_step() -> None:
    capped = progress("implement", loop=4)
    looped = approve(settings(), capped, "loop_cap")
    assert (looped.decision, looped.progress.loop_max) == (Run("implement", 5), 6)
    assert approve(settings(), capped, "loop_cap", loops=5).progress.loop_max == 9
    spent = progress(tokens=260_000)
    assert approve(settings(), spent, "token_cap").progress.tokens_max == 510_000
    assert approve(settings(), spent, "token_cap", tokens=1000).progress.tokens_max == 261_000
    passed = approve(settings(), progress("approve", hitl=True), "approve_step")
    assert passed.decision == Run("review_plan", 1)


def test_fingerprints_ignore_case_numbers_and_spacing() -> None:
    one = fingerprint("./src/keys.py", "Missing check  on line 12")
    assert one == fingerprint("src/keys.py", "missing check on line 40")
    assert one != fingerprint("src/other.py", "missing check on line 12")
    assert len(one) == 12


PERF = {"perf-reviewer": {"cli": "claude/sonnet", "skill": "perf-reviewer"}}
PERF_FLOW = {
    "steps": ["plan", "implement", "review_code", "perf_review"],
    "on_fail": {"review_code": "implement", "perf_review": "implement"},
}


def custom(**agent: Any) -> Settings:
    step = {"role": "perf-reviewer", "kind": "review", "does": "Check hot paths."}
    return settings(
        {"perf-reviewer": PERF["perf-reviewer"] | agent},
        steps={"perf_review": step},
        workflows=WORKFLOWS | {"standard": PERF_FLOW},
    )


def test_a_custom_review_step_routes_like_review_code() -> None:
    routed = after(custom(), progress("perf_review"), fail("p1"))
    assert routed.decision == Run("implement", 2)
    assert routed.progress.streaks == {"perf_review": {"p1": 1}}
    capped = after(custom(), progress("perf_review", loop=4), fail("p1"))
    assert capped.decision == Halt(NEEDS_APPROVAL, "loop cap: 4 of 4", "loop_cap")
    assert after(custom(), progress("review_code"), PASS).decision == Run("perf_review", 1)


def test_a_custom_step_follows_its_agents_switches() -> None:
    assert steps_for(custom(on=False), "standard", hitl=False)[-1] == "review_code"
    halted = before(custom(on=False, blocking=True), progress("perf_review"))
    assert halted.decision == Halt(FAILED, "role perf-reviewer is off and blocking")


HELPER = {"helper": {"cli": "claude/sonnet", "skill": "helper"}}
ADVISE = {"advise": {"role": "helper", "kind": "read", "does": "Note the risks."}}


@pytest.mark.parametrize(
    "order",
    [
        ["advise", "plan", "implement", "review_code"],
        ["plan", "advise", "implement", "review_code"],
        ["plan", "implement", "review_code", "advise"],
        ["plan", "implement", "advise", "approve", "review_code"],
    ],
)
def test_custom_agent_runs_anywhere(order: list[str]) -> None:
    flows = WORKFLOWS | {"standard": {"steps": order}}
    resolved = settings(HELPER, steps=ADVISE, workflows=flows)
    assert first_step(resolved, "standard", hitl=False) == order[0]
    walked: list[str] = []
    routed = before(resolved, progress(order[0]))
    while isinstance(routed.decision, Run):  # as the worker does: before() ahead of each step
        walked.append(routed.decision.step)
        routed = after(resolved, routed.progress, PASS)
        if isinstance(routed.decision, Run):
            routed = before(resolved, routed.progress)
    stop = order.index("approve") if "approve" in order else len(order)
    assert walked == order[:stop]
    expected = Halt(NEEDS_APPROVAL, "waiting for the user's approval", "approve_step")
    assert routed.decision == (expected if "approve" in order else DONE)
