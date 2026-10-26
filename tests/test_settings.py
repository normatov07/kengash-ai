from pathlib import Path

import pytest

from kengash_ai import settings
from kengash_ai.model import UserError
from kengash_ai.store import StorePaths
from kengash_ai.store.seed import ensure_project, ensure_store


@pytest.fixture
def project_file(store_paths: StorePaths) -> Path:
    ensure_store(store_paths)
    return ensure_project(store_paths, "app").settings


def test_package_defaults_are_valid(store_paths: StorePaths) -> None:
    resolved = settings.load(store_paths)
    assert (resolved.loop_max.critical, resolved.merge.mode, resolved.grill.round_size) == (
        6,
        "ask",
        3,
    )
    assert resolved.workflows["critical"].steps[-1] == "security"


def test_unflatten_nests_dotted_keys() -> None:
    nested = settings.unflatten({"loop_max.simple": 3, "loop_max": {"critical": 6}})
    assert nested == {"loop_max": {"simple": 3, "critical": 6}}


def test_unflatten_refuses_conflicts() -> None:
    with pytest.raises(UserError, match="conflicts"):
        settings.unflatten({"merge": "ask", "merge.mode": "auto"})


def test_project_file_overrides_defaults(store_paths: StorePaths, project_file: Path) -> None:
    project_file.write_text(
        "loop_max.critical: 8\nagents:\n  implementer: {cli: claude/sonnet}\n", encoding="utf-8"
    )
    resolved = settings.load(store_paths, "app")
    assert (resolved.loop_max.critical, resolved.loop_max.simple) == (8, 3)
    assert resolved.agents["implementer"].cli == "claude/sonnet"
    assert resolved.agents["implementer"].skill == "implement"


def test_a_workflow_override_replaces_the_whole_workflow(
    store_paths: StorePaths, project_file: Path
) -> None:
    project_file.write_text("workflows:\n  simple: {steps: [plan, implement]}\n", encoding="utf-8")
    assert settings.load(store_paths, "app").workflows["simple"].on_fail == {}


def test_unknown_keys_get_a_suggestion(store_paths: StorePaths, project_file: Path) -> None:
    project_file.write_text("loop_max.critcal: 8\n", encoding="utf-8")
    assert settings.problems(store_paths, "app") == [
        "unknown key loop_max.critcal; did you mean loop_max.critical?"
    ]
    with pytest.raises(UserError, match=r"did you mean loop_max\.critical"):
        settings.load(store_paths, "app")


def test_bad_values_name_the_key(store_paths: StorePaths, project_file: Path) -> None:
    project_file.write_text("merge.mode: sometimes\n", encoding="utf-8")
    [problem] = settings.problems(store_paths, "app")
    assert problem.startswith("merge.mode: ")


def test_workflows_must_use_known_steps(store_paths: StorePaths, project_file: Path) -> None:
    project_file.write_text("workflows:\n  simple: {steps: [plan, deploy]}\n", encoding="utf-8")
    [problem] = settings.problems(store_paths, "app")
    assert problem.startswith("workflows.simple: unknown steps ['deploy']")


def test_get_reads_dotted_keys(store_paths: StorePaths) -> None:
    resolved = settings.load(store_paths)
    assert settings.get(resolved, "loop_max.critical") == 6
    assert settings.get(resolved, "agents.planner.cli") == "claude/opus"
    with pytest.raises(UserError, match="did you mean loop_grant"):
        settings.get(resolved, "loop_grnt")


def test_package_defaults_name_providers_and_the_compactor(store_paths: StorePaths) -> None:
    resolved = settings.load(store_paths)
    assert resolved.memory.compactor == "claude/haiku"
    assert set(resolved.providers) == {"claude", "codex", "antigravity"}
    assert not resolved.provider("claude").user_config
    assert not resolved.agents["implementer"].bypass_permissions
