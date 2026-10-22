from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from super_harness.model import Event, Settings

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


def test_events_keep_extra_fields() -> None:
    event = Event(ts=datetime(2026, 10, 22, tzinfo=UTC), type="step.end", loop=2)
    assert event.model_extra == {"loop": 2}
    assert event.model_dump(mode="json", exclude_none=True) == {
        "ts": "2026-10-22T00:00:00Z",
        "type": "step.end",
        "loop": 2,
    }
