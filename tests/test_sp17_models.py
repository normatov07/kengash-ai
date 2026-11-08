"""Models per agent: importance, live lists, editable everywhere (SP17 spec §3.10)."""

from typing import Any

import pytest
from conftest import write_settings
from typer.testing import CliRunner

from kengash_ai import settings
from kengash_ai.cli import app
from kengash_ai.model import NeedsSetup, ProviderStatus, Settings
from kengash_ai.ops import agent_config, agents, queue
from kengash_ai.store import StorePaths


def _status(models: tuple[str, ...] = (), live: bool = False) -> Any:
    def status(name: str) -> ProviderStatus:
        return ProviderStatus(
            name=name, installed=True, signed_in=True, models=list(models), live_models=live
        )

    return status


def _settings(**agent: Any) -> Settings:
    base = {"cli": "claude/sonnet", "skill": "implement"}
    return Settings(agents={"implementer": base | agent})


def test_the_importance_model_comes_first() -> None:
    resolved = _settings(by_importance={"critical": "claude/opus"})
    pick = agents.pick(resolved, "implementer", _status(), importance="critical")
    assert (pick.provider, pick.model) == ("claude", "opus")


def test_another_importance_uses_the_agents_cli() -> None:
    resolved = _settings(by_importance={"critical": "claude/opus"})
    pick = agents.pick(resolved, "implementer", _status(), importance="simple")
    assert pick.model == "sonnet"


def test_the_chain_goes_on_to_cli_then_fallback() -> None:
    resolved = _settings(
        cli="antigravity/flash",
        by_importance={"critical": "codex"},
        fallback=["claude/sonnet"],
    )
    pick = agents.pick(resolved, "implementer", _status(), importance="critical", skip={"codex"})
    assert (pick.provider, pick.fallback) == ("antigravity", True)
    last = agents.pick(
        resolved, "implementer", _status(), importance="critical", skip={"codex", "antigravity"}
    )
    assert last.provider == "claude"


def test_a_model_the_live_list_lacks_is_skipped() -> None:
    resolved = _settings(cli="antigravity/gone", fallback=["antigravity/here"])
    pick = agents.pick(resolved, "implementer", _status(("here",), live=True))
    assert pick.model == "here"


def test_every_model_missing_needs_setup() -> None:
    resolved = _settings(cli="antigravity/gone")
    with pytest.raises(NeedsSetup, match="no model gone"):
        agents.pick(resolved, "implementer", _status(("here",), live=True))


def test_aliases_are_no_live_list() -> None:
    resolved = _settings(cli="claude/claude-opus-5-5")
    pick = agents.pick(resolved, "implementer", _status(("opus",)))
    assert pick.model == "claude-opus-5-5"


def test_an_empty_live_list_skips_nothing() -> None:
    resolved = _settings(cli="antigravity/flash")
    assert agents.pick(resolved, "implementer", _status((), live=True)).model == "flash"


def test_the_queue_names_the_importance_provider() -> None:
    resolved = Settings(
        agents={
            "implementer": {
                "cli": "claude/sonnet",
                "skill": "implement",
                "by_importance": {"critical": "codex"},
            }
        }
    )
    assert queue._provider(resolved, "implement", "critical") == "codex"
    assert queue._provider(resolved, "implement", "simple") == "claude"


def test_edit_agent_sets_by_importance(store_paths: StorePaths, registered_repo: Any) -> None:
    patch = agent_config.AgentPatch(by_importance={"critical": "claude/opus"})
    agent_config.edit_agent("code-reviewer", patch, project="payments-api", by="t")
    found = agent_config.show_agent("code-reviewer", project="payments-api")
    assert found.by_importance == {"critical": "claude/opus"}


def test_the_cli_adds_and_removes_one_importance(
    store_paths: StorePaths, registered_repo: Any
) -> None:
    runner = CliRunner()
    args = ["agent", "edit", "implementer", "--project", "payments-api"]
    assert runner.invoke(app, [*args, "--model-for", "critical=claude/opus"]).exit_code == 0
    assert runner.invoke(app, [*args, "--model-for", "simple=claude/haiku"]).exit_code == 0
    found = agent_config.show_agent("implementer", project="payments-api")
    assert found.by_importance == {"critical": "claude/opus", "simple": "claude/haiku"}
    assert runner.invoke(app, [*args, "--model-for", "simple="]).exit_code == 0
    found = agent_config.show_agent("implementer", project="payments-api")
    assert found.by_importance == {"critical": "claude/opus"}
    shown = runner.invoke(app, ["agent", "show", "implementer", "--project", "payments-api"])
    assert "for critical: claude/opus" in shown.output


def test_a_bad_model_for_is_refused(store_paths: StorePaths, registered_repo: Any) -> None:
    result = CliRunner().invoke(
        app, ["agent", "edit", "implementer", "--project", "payments-api", "--model-for", "nope"]
    )
    assert result.exit_code != 0


def test_the_agy_list_is_live() -> None:
    from kengash_ai.adapters.antigravity import Antigravity
    from kengash_ai.adapters.claude import Claude

    assert Antigravity.LIVE_MODELS and not Claude.LIVE_MODELS


def test_a_project_can_clear_an_importance_the_defaults_set(
    store_paths: StorePaths, registered_repo: Any
) -> None:
    found = agent_config.show_agent("code-reviewer", project="payments-api")
    assert found.by_importance == {"critical": "claude/opus"}  # the package default
    args = ["agent", "edit", "code-reviewer", "--project", "payments-api"]
    assert CliRunner().invoke(app, [*args, "--model-for", "critical="]).exit_code == 0
    found = agent_config.show_agent("code-reviewer", project="payments-api")
    assert found.by_importance == {}


def test_the_shell_honours_skip() -> None:
    resolved = Settings(agents={"test-runner": {"cli": "shell", "skill": "run-tests"}})
    with pytest.raises(NeedsSetup):
        agents.pick(resolved, "test-runner", _status(), skip={"shell"})


def test_the_chain_reaches_the_agents_cli_on_the_same_provider() -> None:
    resolved = _settings(by_importance={"critical": "claude/opus"})
    pick = agents.pick(
        resolved, "implementer", _status(), importance="critical", skip={"claude/opus"}
    )
    assert (pick.provider, pick.model, pick.fallback) == ("claude", "sonnet", True)


def test_a_scope_that_picks_a_cli_drops_the_inherited_models(
    store_paths: StorePaths, registered_repo: Any
) -> None:
    write_settings(store_paths, "agents:\n  code-reviewer: {cli: codex}\n")
    assert settings.load(store_paths, "payments-api").agents["code-reviewer"].by_importance == {}


def test_a_scope_that_sets_only_the_models_keeps_the_inherited_cli(
    store_paths: StorePaths, registered_repo: Any
) -> None:
    text = "agents:\n  code-reviewer: {by_importance: {simple: claude/haiku}}\n"
    write_settings(store_paths, text)
    agent = settings.load(store_paths, "payments-api").agents["code-reviewer"]
    assert (agent.cli, agent.by_importance) == ("claude/sonnet", {"simple": "claude/haiku"})
