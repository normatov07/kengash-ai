"""Agent choice: the role's CLI, then its fallbacks (SP3 spec decision 7)."""

from collections.abc import Callable
from pathlib import Path

import pytest

from super_harness import settings
from super_harness.model import NeedsSetup, ProviderStatus
from super_harness.ops import agents
from super_harness.ops.agents import Pick
from super_harness.store import StorePaths


def status(**usable: bool) -> Callable[[str], ProviderStatus]:
    def detect(name: str) -> ProviderStatus:
        ok = usable.get(name, True)
        return ProviderStatus(
            name=name, installed=ok, signed_in=ok, hint="" if ok else f"install {name}"
        )

    return detect


def test_pick_prefers_the_agent_then_its_fallbacks(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    resolved = settings.load(store_paths)
    assert agents.pick(resolved, "implementer", status()) == Pick(
        "implementer", "codex", None, False
    )
    assert agents.pick(resolved, "implementer", status(codex=False)) == Pick(
        "implementer", "claude", "sonnet", True
    )
    assert agents.pick(resolved, "implementer", status(), skip={"codex"}).provider == "claude"
    assert agents.pick(resolved, "test-runner", status()) == Pick(
        "test-runner", "shell", None, False
    )
    with pytest.raises(
        NeedsSetup, match="plan-reviewer cannot run: codex not installed; install codex"
    ):
        agents.pick(resolved, "plan-reviewer", status(codex=False))
