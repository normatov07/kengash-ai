import re
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from kengash_ai.model import PROVIDERS, Event, ProviderOptions, Settings, split_cli
from kengash_ai.model.settings import BUILTIN_SKILLS

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
        (
            {"agents": {**PERF_AGENTS, "perf-reviewer": {"cli": "shell", "skill": "x"}}},
            "needs a model CLI",
        ),
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


@pytest.mark.parametrize(
    "data",
    [
        {"agents": {**AGENTS, "doc-writer": {"cli": "gemini", "skill": "sync-docs"}}},
        {
            "agents": {
                **AGENTS,
                "implementer": {"cli": "codex", "skill": "x", "fallback": ["gemini"]},
            }
        },
        {"memory": {"compactor": "gemini/flash"}},
        {"plan": {"reviewer": "gemini"}},
        {"providers": {"gemini": {"allow_api_key": False}}},
    ],
)
def test_gemini_is_replaced_by_antigravity(data: dict[str, Any]) -> None:
    assert PROVIDERS == ("claude", "codex", "antigravity")
    with pytest.raises(ValidationError, match="gemini is replaced by antigravity"):
        Settings.model_validate(data)


def test_the_legacy_gemini_slot_is_dropped() -> None:
    legacy = {"claude": 3, "codex": 3, "antigravity": 2, "gemini": 0}  # every old project has it
    settings = Settings.model_validate({"sessions": {"per_provider": legacy}})
    assert settings.sessions.per_provider == {"claude": 3, "codex": 3, "antigravity": 2}
    assert Settings().sessions.per_provider == {"claude": 3, "codex": 3, "antigravity": 2}


FLOWS: dict[str, Any] = {
    "simple": {"steps": ["plan", "implement", "review_code"]},
    "standard": {"steps": ["plan", "implement", "review_code"]},
    "critical": {"steps": ["plan", "implement", "review_code"]},
}


def test_builtin_skills_are_fixed() -> None:
    agents = {**AGENTS, "planner": {"cli": "claude", "skill": "other"}}
    message = (
        "agents.planner.skill is fixed at plan; set it back, or copy the agent "
        "(kengash agent copy planner <new>) to change what it does"
    )
    with pytest.raises(ValidationError, match=re.escape(message)):
        Settings.model_validate({"agents": agents})
    assert BUILTIN_SKILLS["security-reviewer"] == "review-security"


def test_routing_defaults_and_validation() -> None:
    plain = Settings.model_validate({"agents": AGENTS, "workflows": FLOWS})
    assert plain.workflow_for("critical") == "critical"
    hotfix = {**FLOWS, "hotfix": {"steps": ["implement"]}}
    routed = Settings.model_validate(
        {"agents": AGENTS, "workflows": hotfix, "routing": {"critical": "hotfix"}}
    )
    assert routed.workflow_for("critical") == "hotfix" and routed.workflow_for("simple") == "simple"
    with pytest.raises(ValidationError, match=re.escape("routing.critical: no workflow hotfix")):
        Settings.model_validate(
            {"agents": AGENTS, "workflows": FLOWS, "routing": {"critical": "hotfix"}}
        )
    with pytest.raises(ValidationError, match="routing: unknown importance urgent"):
        Settings.model_validate(
            {"agents": AGENTS, "workflows": FLOWS, "routing": {"urgent": "simple"}}
        )


def test_on_fail_sends_back_only() -> None:
    flow = {"steps": ["plan", "implement", "review_code"], "on_fail": {"plan": "review_code"}}
    message = "on_fail edges must send back to an earlier step: plan->review_code"
    with pytest.raises(ValidationError, match=re.escape(message)):
        Settings.model_validate({"agents": AGENTS, "workflows": {"x": flow}})


def test_workflow_names() -> None:
    with pytest.raises(
        ValidationError, match=re.escape("workflow name must match [a-z][a-z0-9_-]{0,30}")
    ):
        Settings.model_validate({"agents": AGENTS, "workflows": {"Hot Fix": {"steps": ["plan"]}}})
    assert Settings.model_validate(
        {"agents": AGENTS, "workflows": {"hot-fix_2": {"steps": ["plan"]}}}
    )


def test_a_step_appears_once() -> None:
    with pytest.raises(ValidationError, match=re.escape("workflows.x: step plan appears twice")):
        Settings.model_validate({"agents": AGENTS, "workflows": {"x": {"steps": ["plan", "plan"]}}})


@pytest.mark.parametrize("cli", ["claude/", "claude/opus 4", "claude/" + "x" * 101])
def test_models_are_one_word(cli: str) -> None:
    with pytest.raises(ValidationError, match=re.escape(f"model must be one word: {cli}")):
        Settings.model_validate(
            {"agents": {**AGENTS, "implementer": {"cli": cli, "skill": "implement"}}}
        )


def test_model_names_may_carry_brackets_and_dots() -> None:
    agents = {**AGENTS, "implementer": {"cli": "claude/opus[1m]", "skill": "implement"}}
    assert (
        Settings.model_validate({"agents": agents}).agents["implementer"].cli == "claude/opus[1m]"
    )
    assert Settings.model_validate({"memory": {"compactor": "antigravity/gemini-3.8-flash-low"}})


def test_loop_start_defaults_to_ask_and_takes_auto() -> None:
    assert Settings().loop_start == "ask"
    assert Settings.model_validate({"loop_start": "auto"}).loop_start == "auto"


def test_loop_start_refuses_other_values() -> None:
    with pytest.raises(ValidationError, match="Input should be 'ask' or 'auto'"):
        Settings.model_validate({"loop_start": "always"})
