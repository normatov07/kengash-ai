"""doctor's provider and trust checks (SP3 spec §10)."""

from pathlib import Path

from conftest import FakeClis, write_settings

from super_harness import settings
from super_harness.ops.providers import check_providers, trust_notice
from super_harness.store import StorePaths


def test_every_provider_usable_reports_nothing(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    assert check_providers(store_paths) == []


def test_a_missing_provider_without_fallback_blocks(
    registered_repo: Path, store_paths: StorePaths, fake_clis: FakeClis
) -> None:
    fake_clis.hide("codex")
    [check] = check_providers(store_paths)
    assert check.blocking and check.message == (
        "codex: not installed; used by plan-reviewer, implementer; "
        "install the Codex CLI (npm i -g @openai/codex), then run `codex login`"
    )


def test_a_fallback_only_use_warns(
    registered_repo: Path, store_paths: StorePaths, fake_clis: FakeClis
) -> None:
    fake_clis.sign_out("claude")
    write_settings(
        store_paths,
        "agents.planner.cli: codex\nagents.code-reviewer.cli: codex\n"
        "agents.security-reviewer.cli: codex\nmemory.compactor: codex\n",
    )
    [check] = check_providers(store_paths)
    assert not check.blocking
    assert (
        check.message
        == "claude: signed out; used by implementer; run `claude` and sign in with /login"
    )


def test_disabled_agents_are_not_checked(
    registered_repo: Path, store_paths: StorePaths, fake_clis: FakeClis
) -> None:
    fake_clis.hide("agy")
    assert check_providers(store_paths) == []


def test_gemini_points_to_antigravity(registered_repo: Path, store_paths: StorePaths) -> None:
    write_settings(
        store_paths,
        "agents.doc-writer: {on: true, cli: gemini, skill: sync-docs}\n",
        slugs=("payments-api",),
    )
    [problem] = settings.problems(store_paths, "payments-api")
    assert "gemini is replaced by antigravity" in problem


def test_a_claude_login_without_subscription_warns(
    registered_repo: Path, store_paths: StorePaths, fake_clis: FakeClis
) -> None:
    fake_clis.auth_method("console")
    [check] = check_providers(store_paths)
    assert not check.blocking and check.message == (
        "claude: signed in with console, not a claude.ai subscription; workers will bill it"
    )
    write_settings(store_paths, "providers.claude.allow_api_key: true\n", slugs=(None,))
    assert check_providers(store_paths) == []


def test_trust_notice_shows_once_per_change(registered_repo: Path, store_paths: StorePaths) -> None:
    assert trust_notice(store_paths, "payments-api", registered_repo) is None
    (registered_repo / ".mcp.json").write_text('{"mcpServers": {}}')
    settings = registered_repo / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text('{"hooks": {"PostToolUse": []}}')
    assert trust_notice(store_paths, "payments-api", registered_repo) == (
        "repo ships .claude/settings.json hooks and .mcp.json; "
        "workers run them without a trust prompt"
    )
    assert trust_notice(store_paths, "payments-api", registered_repo) is None
    (registered_repo / ".mcp.json").write_text('{"mcpServers": {"x": {}}}')
    assert trust_notice(store_paths, "payments-api", registered_repo) is not None
