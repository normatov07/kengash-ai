"""Project checks: detected test and lint commands, a checks step, old defaults (SP12 §5)."""

import json
from pathlib import Path

import pytest
from conftest import git

from kengash_ai import settings
from kengash_ai.ops import hygiene, projects
from kengash_ai.store import StorePaths
from kengash_ai.store.seed import ensure_store

FILES: dict[str, tuple[dict[str, str], tuple[str, str]]] = {
    "flutter": (
        {"pubspec.yaml": "name: app\ndependencies:\n  flutter:\n    sdk: flutter\n"},
        ("flutter test", "flutter analyze"),
    ),
    "dart": ({"pubspec.yaml": "name: tool\n"}, ("dart test", "dart analyze")),
    "uv": (
        {"uv.lock": "", "pyproject.toml": "[tool.ruff]\nline-length = 100\n"},
        ("uv run pytest -q", "uv run ruff check"),
    ),
    "uv-no-ruff": ({"uv.lock": "", "pyproject.toml": "[project]\n"}, ("uv run pytest -q", "")),
    "node": (
        {"package.json": json.dumps({"scripts": {"test": "jest", "lint": "eslint ."}})},
        ("npm test", "npm run lint"),
    ),
    "go": ({"go.mod": "module x\n"}, ("go test ./...", "go vet ./...")),
    "rust": ({"Cargo.toml": "[package]\n"}, ("cargo test", "cargo clippy")),
    "none": ({"README.md": "hi\n"}, ("", "")),
}


@pytest.mark.parametrize("kind", sorted(FILES))
def test_detects(kind: str, tmp_path: Path) -> None:
    files, expected = FILES[kind]
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    assert hygiene.detect_commands(tmp_path) == expected


def test_init_writes_commands_and_the_checks_step(store_paths: StorePaths, repo: Path) -> None:
    (repo / "go.mod").write_text("module x\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "go")
    slug = projects.init_project(repo).slug
    resolved = settings.load(store_paths, slug)
    assert (resolved.project.test_cmd, resolved.project.lint_cmd) == (
        "go test ./...",
        "go vet ./...",
    )
    assert resolved.agents["test-runner"].on is True
    for name in ("standard", "critical"):
        flow = resolved.workflows[name]
        assert flow.steps[flow.steps.index("implement") + 1] == "run_tests"
        assert flow.on_fail["run_tests"] == "implement"


OLD = """tokens.per_ticket_max: 250000   # my ceiling
fallback_on_rate_limit: true
agents:
  doc-writer: {on: false, cli: antigravity, skill: sync-docs}
"""


def test_doctor_reports_and_fixes_old_defaults_keeping_comments(store_paths: StorePaths) -> None:
    ensure_store(store_paths)
    defaults = store_paths.defaults / "SETTINGS.md"
    defaults.write_text("version: 1\n" + OLD, encoding="utf-8")
    messages = [problem.message for problem in projects.doctor().problems]
    for key in ("tokens.per_ticket_max", "fallback_on_rate_limit", "agents.doc-writer.fallback"):
        assert f"defaults still has the old default {key}; run: kengash doctor --fix" in messages
    projects.doctor(fix=True)
    text = defaults.read_text(encoding="utf-8")
    assert "tokens.per_ticket_max: 1000000" in text and "# my ceiling" in text
    assert "fallback_on_rate_limit" not in text and "fallback_on_error: true" in text
    assert settings.load(store_paths).agents["doc-writer"].fallback == ["claude/sonnet"]
    assert not any("old default" in p.message for p in projects.doctor().problems)


def test_fix_never_touches_a_changed_value(store_paths: StorePaths) -> None:
    ensure_store(store_paths)
    defaults = store_paths.defaults / "SETTINGS.md"
    defaults.write_text("version: 1\ntokens.per_ticket_max: 400000\n", encoding="utf-8")
    assert not any("tokens.per_ticket_max" in p.message for p in projects.doctor().problems)
    projects.doctor(fix=True)
    assert "tokens.per_ticket_max: 400000" in defaults.read_text(encoding="utf-8")


def test_a_project_without_a_test_command_is_named(store_paths: StorePaths, repo: Path) -> None:
    slug = projects.init_project(repo).slug  # nothing to detect: README only
    (repo / "go.mod").write_text("module x\n", encoding="utf-8")
    messages = [problem.message for problem in projects.doctor().problems]
    assert (
        f"project {slug} has no test command; detected: go test ./...; run: kengash doctor --fix"
        in messages
    )
    projects.doctor(fix=True)
    assert settings.load(store_paths, slug).project.test_cmd == "go test ./..."


def test_agents_without_fallback_are_info(store_paths: StorePaths) -> None:
    ensure_store(store_paths)
    notes = projects.doctor().notes
    assert [note.message for note in notes if note.message.startswith("defaults:")] == [
        "defaults: agents without a fallback: "
        "code-reviewer, plan-reviewer, planner, security-reviewer"
    ]
