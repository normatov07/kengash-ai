"""SP17 contracts: the new settings and their defaults (spec §4)."""

import pytest
from pydantic import ValidationError

from kengash_ai.model import PlanOutput, RelayIntent, Settings, TicketState


def _agent(**fields: object) -> dict[str, object]:
    return {"cli": "claude", "skill": "implement", **fields}


def test_defaults_match_the_spec() -> None:
    found = Settings()
    assert found.steering.model_dump() == {
        "soft_min": 20,
        "wrap_min": 10,
        "turns": 2,
        "poll_max": 8,
        "full_runs_max": 2,
    }
    assert found.paths.max_overlap == 2
    assert "*.g.dart" in found.paths.shared
    assert found.context.max_kib == 64
    assert found.checks.parallel == 0
    assert found.plan.max_files == 12
    assert found.review.block_on == ["high", "medium"]
    assert found.loop_relay is True


def test_by_importance_takes_a_known_cli() -> None:
    agent = Settings(agents={"implementer": _agent(by_importance={"critical": "claude/opus"})})
    assert agent.agents["implementer"].by_importance == {"critical": "claude/opus"}


@pytest.mark.parametrize(
    "mapping",
    [{"urgent": "claude/opus"}, {"critical": "nope/x"}, {"critical": "shell"}],
)
def test_by_importance_refuses_what_cannot_run(mapping: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        Settings(agents={"implementer": _agent(by_importance=mapping)})


def test_a_plan_may_carry_parts() -> None:
    part = {"title": "a", "scope": "s", "acceptance": ["x"], "files": ["a.py"], "after": []}
    output = PlanOutput(summary="s", handoff="h", parts=[part])
    assert output.parts[0].files == ["a.py"]
    assert PlanOutput(summary="s", handoff="h").parts == []


def test_runtime_shapes() -> None:
    assert TicketState().seen == {}
    assert RelayIntent().scopes == []
