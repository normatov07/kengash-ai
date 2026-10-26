from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from super_harness.model import Event, ProviderOptions, Settings, split_cli

AGENTS: dict[str, Any] = {
    "planner": {"cli": "claude/opus", "skill": "plan"},
    "implementer": {"cli": "codex", "skill": "implement"},
    "code-reviewer": {"cli": "claude/opus", "skill": "review-code"},
}


def test_defaults_need_no_input() -> None:
    settings = Settings()
    assert (settings.loop_max.critical, settings.merge.mode, settings.sessions.max) == (6, "ask", 8)


def test_workflow_steps_must_be_known() -> None:
    with pytest.raises(ValidationError, match=r"unknown steps \['deploy'\]"):
        Settings.model_validate({"agents": AGENTS, "workflows": {"x": {"steps": ["deploy"]}}})


def test_on_fail_edges_stay_inside_the_workflow() -> None:
    workflow = {"steps": ["plan", "implement"], "on_fail": {"review_code": "implement"}}
    with pytest.raises(ValidationError, match="on_fail edges must join steps"):
        Settings.model_validate({"agents": AGENTS, "workflows": {"x": workflow}})


def test_every_step_needs_its_agent() -> None:
    workflow = {"steps": ["plan", "security"]}
    with pytest.raises(ValidationError, match="security: security-reviewer"):
        Settings.model_validate({"agents": AGENTS, "workflows": {"x": workflow}})


def test_provider_slots_cannot_be_negative() -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        Settings.model_validate({"sessions": {"per_provider": {"claude": -1}}})


def test_event_times_are_kept_in_utc() -> None:
    plus_five = timezone(timedelta(hours=5))
    event = Event(ts=datetime(2026, 10, 22, 2, 0, tzinfo=plus_five), type="a")
    assert event.model_dump(mode="json")["ts"] == "2026-10-21T21:00:00Z"
    assert Event(ts=datetime(2026, 10, 22), type="a").ts.tzinfo is UTC


def test_events_keep_extra_fields() -> None:
    event = Event(ts=datetime(2026, 10, 22, tzinfo=UTC), type="step.end", loop=2)
    assert event.model_extra == {"loop": 2}
    assert event.model_dump(mode="json", exclude_none=True) == {
        "ts": "2026-10-22T00:00:00Z",
        "type": "step.end",
        "loop": 2,
    }


def test_agents_and_fallbacks_name_known_providers() -> None:
    assert not Settings.model_validate({"agents": AGENTS}).agents["planner"].bypass_permissions
    planner = {"cli": "cluade/opus", "skill": "plan"}
    with pytest.raises(ValidationError, match="unknown provider 'cluade'"):
        Settings.model_validate({"agents": {**AGENTS, "planner": planner}})
    implementer = {"cli": "codex", "skill": "implement", "fallback": ["shell"]}
    with pytest.raises(ValidationError, match="unknown provider 'shell'"):
        Settings.model_validate({"agents": {**AGENTS, "implementer": implementer}})


def test_the_compactor_names_a_model_provider() -> None:
    assert Settings().memory.compactor == "claude/haiku"
    with pytest.raises(ValidationError, match="unknown provider 'llama'"):
        Settings.model_validate({"memory": {"compactor": "llama/3"}})


def test_provider_options_default_per_provider() -> None:
    settings = Settings.model_validate({"providers": {"codex": {"user_config": True}}})
    assert settings.provider("codex").user_config is True
    assert settings.provider("claude") == ProviderOptions()
    with pytest.raises(ValidationError, match=r"unknown providers \['cursor'\]"):
        Settings.model_validate({"providers": {"cursor": {}}})


def test_split_cli_separates_provider_and_model() -> None:
    assert split_cli("claude/opus") == ("claude", "opus")
    assert split_cli("codex") == ("codex", None)


def test_the_plan_reviewer_is_different_provider_or_a_known_provider() -> None:
    assert Settings.model_validate({"plan": {"reviewer": "codex/gpt-5"}}).plan.reviewer == (
        "codex/gpt-5"
    )
    with pytest.raises(ValidationError, match="unknown provider"):
        Settings.model_validate({"plan": {"reviewer": "same-provider"}})


PERF_AGENTS: dict[str, Any] = {**AGENTS, "perf-reviewer": {"cli": "claude/sonnet", "skill": "x"}}
PERF_STEP: dict[str, Any] = {"role": "perf-reviewer", "kind": "review", "does": "Check hot paths."}


def _custom(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "agents": PERF_AGENTS,
        "steps": {"perf_review": PERF_STEP},
        "workflows": {
            "simple": {
                "steps": ["plan", "implement", "review_code", "perf_review"],
                "on_fail": {"review_code": "implement", "perf_review": "implement"},
            }
        },
    }
    return {**data, **changes}


def test_a_custom_step_validates_and_resolves() -> None:
    settings = Settings.model_validate(_custom())
    assert settings.role_of("perf_review") == "perf-reviewer"
    assert settings.kind_of("perf_review") == "review"
    assert (settings.kind_of("run_tests"), settings.kind_of("implement")) == ("check", "edit")
    assert settings.role_of("approve") is None and settings.role_of("deploy") is None
    assert settings.step_names()[:2] == ["plan", "review_plan"]
    assert settings.step_names()[-1] == "perf_review"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"steps": {"security": PERF_STEP}}, "built-in"),
        ({"steps": {"Perf": PERF_STEP}}, "step name"),
        ({"steps": {"perf_review": {**PERF_STEP, "role": "ghost"}}}, "no agent"),
        ({"steps": {"perf_review": {**PERF_STEP, "does": "one\ntwo"}}}, "one line"),
        ({"steps": {"perf_review": {**PERF_STEP, "does": "x" * 201}}}, "one line"),
        ({"steps": {"perf_review": {**PERF_STEP, "kind": "check"}}}, "kind"),
        ({"workflows": {"x": {"steps": ["plan", "perf_tune"]}}}, r"unknown steps \['perf_tune'\]"),
        (
            {"steps": {"perf_review": {**PERF_STEP, "kind": "edit"}}},
            "only review steps",
        ),
        (
            {
                "agents": {**PERF_AGENTS, "Perf_Reviewer": PERF_AGENTS["planner"]},
                "steps": {"perf_review": {**PERF_STEP, "role": "Perf_Reviewer"}},
            },
            "role name",
        ),
    ],
)
def test_custom_step_problems(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings.model_validate(_custom(**changes))
