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
        "auto",
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


def test_old_fallback_key_is_read(store_paths: StorePaths) -> None:
    ensure_store(store_paths)
    defaults = store_paths.defaults / "SETTINGS.md"
    text = defaults.read_text(encoding="utf-8").replace("fallback_on_error: true", "")
    defaults.write_text(text + "fallback_on_rate_limit: false\n", encoding="utf-8")
    assert settings.load(store_paths).fallback_on_error is False


def test_both_fallback_keys_in_one_file_are_refused(store_paths: StorePaths) -> None:
    ensure_store(store_paths)
    defaults = store_paths.defaults / "SETTINGS.md"
    defaults.write_text(
        defaults.read_text(encoding="utf-8") + "fallback_on_rate_limit: true\n", encoding="utf-8"
    )
    assert settings.problems(store_paths) == [
        "defaults/SETTINGS.md: use fallback_on_error only, not fallback_on_rate_limit"
    ]


def test_setting_the_new_key_drops_the_old(store_paths: StorePaths) -> None:
    ensure_store(store_paths)
    defaults = store_paths.defaults / "SETTINGS.md"
    text = defaults.read_text(encoding="utf-8").replace("fallback_on_error: true", "")
    defaults.write_text(text + "fallback_on_rate_limit: true  # mine\n", encoding="utf-8")
    assert settings.set_values(store_paths, None, {"fallback_on_error": False}) == [
        "fallback_on_error",
        "fallback_on_rate_limit",
    ]
    after = defaults.read_text(encoding="utf-8")
    assert "fallback_on_rate_limit" not in after and "fallback_on_error: false" in after
    assert settings.load(store_paths).fallback_on_error is False


def test_the_new_key_takes_the_old_keys_line(store_paths: StorePaths) -> None:
    ensure_store(store_paths)
    defaults = store_paths.defaults / "SETTINGS.md"
    text = defaults.read_text(encoding="utf-8").replace("fallback_on_error: true\n", "")
    lines = text.splitlines(keepends=True)
    lines.insert(1, "fallback_on_rate_limit: true  # mine\n")
    defaults.write_text("".join(lines), encoding="utf-8")
    settings.set_values(store_paths, None, {"fallback_on_error": False})
    after = defaults.read_text(encoding="utf-8").splitlines(keepends=True)
    assert after[1] == "fallback_on_error: false  # mine\n"
    assert len(after) == len(lines)


def test_seed_doc_writer_fallback(store_paths: StorePaths) -> None:
    ensure_store(store_paths)
    resolved = settings.load(store_paths)
    assert resolved.agents["doc-writer"].fallback == ["claude/sonnet"]
    assert resolved.tokens.per_ticket_max == 3_000_000


def test_watch_defaults_and_a_bad_value(store_paths: StorePaths) -> None:
    ensure_store(store_paths)
    watch = settings.load(store_paths).watch
    assert (watch.tabs, watch.terminal, watch.notify) == ("auto", "", True)
    defaults = store_paths.defaults / "SETTINGS.md"
    text = defaults.read_text(encoding="utf-8").replace("watch.tabs: auto", "watch.tabs: never")
    defaults.write_text(text, encoding="utf-8")
    assert settings.problems(store_paths)[0].startswith("watch.tabs")
