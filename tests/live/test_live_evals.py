"""The eval runner on real conductors (SP4 spec §5): a one-step skill whose heredoc
`harness plan new` must land in the scenario's store. Opt in with `-m live`."""

from pathlib import Path

import pytest

from kengash_ai import adapters
from kengash_ai.model import EvalScenario
from kengash_ai.ops import evals

pytestmark = pytest.mark.live
SKILL = """\
---
name: probe-plan
description: Use when the user types /probe-plan.
disable-model-invocation: true
---
1. Run this shell command exactly as written:

```
harness plan new --mode direct --title Probe <<'EOF'
Add add(a, b) to calc.py.
EOF
```

2. Reply with the line it printed.
"""
SCENARIO = EvalScenario.model_validate(
    {
        "skill": "probe-plan",
        "turns": ["/probe-plan"],
        "expect": {
            "journal": ["plan.created"],
            "plans": {"count": 1, "fields": {"title": "Probe", "mode": "direct"}},
            "reply": ["plan "],
        },
        "timeout_s": 300,
    }
)


@pytest.fixture
def fake_clis() -> None:
    """Replaces the autouse fakes: these runs use the real CLIs."""


@pytest.mark.parametrize("agent", ["claude", "antigravity", "codex"])
def test_a_skill_runs_harness_in_the_scenario_store(
    agent: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not adapters.get(agent, runtime=tmp_path / "runtime").detect().usable:
        pytest.skip(f"{agent} is not installed and signed in")
    monkeypatch.delenv("HARNESS_HOME", raising=False)
    source = tmp_path / "skills" / "probe-plan"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text(SKILL, encoding="utf-8")
    run = evals.run_scenario(
        "probe-plan/one",
        SCENARIO,
        agent,
        work=tmp_path / "work",
        model=evals.CHEAPEST[agent],
        source=source.parent,
    )
    log = (tmp_path / "work" / "turn-1.out").read_text(encoding="utf-8", errors="replace")[-2000:]
    assert run.passed, f"{run.failure}\n{log}"
