from datetime import UTC, datetime, timedelta, timezone
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
