"""Skill evals: scenarios, headless conductor runs, expectations (SP4 spec decisions 11-13)."""

from pathlib import Path

import pytest

from super_harness.model import EvalScenario, UserError
from super_harness.ops import evals

SCENARIO = """\
skill: to-plan
description: a direct plan from a short prompt
files:
  calc.py: "def sub(a, b):\\n    return a - b\\n"
settings: "plan.review_max: 0\\n"
setup:
  - args: [plan, new, --mode, direct, --title, Seed]
    stdin: "Seed prompt."
    save: seed
turns:
  - "/to-plan Add add(a, b) to calc.py"
expect:
  journal: [plan.created]
  absent: [plan.approved]
  plans: {min: 1, fields: {mode: direct}}
"""


def write(folder: Path, name: str, text: str) -> Path:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_load_reads_a_scenario(tmp_path: Path) -> None:
    scenario = evals.load(write(tmp_path, "to-plan/direct.yaml", SCENARIO))
    assert isinstance(scenario, EvalScenario)
    assert (scenario.skill, scenario.setup[0].save, scenario.timeout_s) == ("to-plan", "seed", 900)
    assert scenario.expect.plans is not None and scenario.expect.plans.fields == {"mode": "direct"}


def test_load_names_the_file_and_the_bad_key(tmp_path: Path) -> None:
    path = write(tmp_path, "to-plan/typo.yaml", SCENARIO.replace("absent:", "absnet:"))
    with pytest.raises(UserError, match=r"typo\.yaml: .*absnet"):
        evals.load(path)


def test_scenarios_lists_one_skill_or_all(tmp_path: Path) -> None:
    write(tmp_path, "to-plan/b.yaml", SCENARIO)
    write(tmp_path, "to-plan/a.yaml", SCENARIO)
    write(tmp_path, "to-ticket/one.yaml", SCENARIO.replace("to-plan", "to-ticket"))
    assert [name for name, _ in evals.scenarios(tmp_path, "to-plan")] == ["to-plan/a", "to-plan/b"]
    assert len(evals.scenarios(tmp_path, None)) == 3
    with pytest.raises(UserError, match="no eval scenarios for to-loop"):
        evals.scenarios(tmp_path, "to-loop")


def test_fill_replaces_known_names_only() -> None:
    assert evals.fill("/to-ticket {plan} {other}", {"plan": "a1b2c3d4"}) == (
        "/to-ticket a1b2c3d4 {other}"
    )
