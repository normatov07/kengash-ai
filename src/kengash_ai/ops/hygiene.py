"""Project hygiene (SP12 spec §5): detected test and lint commands, a checks step that
runs them, and settings still at an old package default; `init` and `doctor` use it."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kengash_ai import settings
from kengash_ai.model import KengashError, UserError
from kengash_ai.ops import configure
from kengash_ai.store.paths import StorePaths
from kengash_ai.store.registry import load_registry

BY = "kengash"
CHECKED = ("standard", "critical")  # the workflows a detected project gets `run_tests` in
NEW_TOKEN_CAP = 1_000_000
OLD_TOKEN_CAP = 250_000
FALLBACK = ["claude/sonnet"]


@dataclass
class Note:
    """One doctor line: a problem, a fix made, or information."""

    message: str
    slug: str | None = None
    fixed: bool = False
    warning: bool = True
    info: bool = False


def detect_commands(repo: Path) -> tuple[str, str]:
    """`(test_cmd, lint_cmd)` for the project kind found in `repo`; empty when unknown."""
    pubspec = repo / "pubspec.yaml"
    if pubspec.is_file():
        flutter = "flutter" in pubspec.read_text(encoding="utf-8", errors="replace")
        tool = "flutter" if flutter else "dart"
        return f"{tool} test", f"{tool} analyze"
    if (repo / "uv.lock").is_file():
        pyproject = repo / "pyproject.toml"
        text = (
            pyproject.read_text(encoding="utf-8", errors="replace") if pyproject.is_file() else ""
        )
        ruff = (
            "[tool.ruff" in text
            or (repo / "ruff.toml").is_file()
            or (repo / ".ruff.toml").is_file()
        )
        return "uv run pytest -q", "uv run ruff check" if ruff else ""
    package = repo / "package.json"
    if package.is_file():
        try:
            scripts = json.loads(package.read_text(encoding="utf-8")).get("scripts") or {}
        except (json.JSONDecodeError, AttributeError):
            scripts = {}
        return ("npm test" if "test" in scripts else ""), (
            "npm run lint" if "lint" in scripts else ""
        )
    if (repo / "go.mod").is_file():
        return "go test ./...", "go vet ./..."
    if (repo / "Cargo.toml").is_file():
        return "cargo test", "cargo clippy"
    return "", ""


def check_changes(paths: StorePaths, slug: str, test: str, lint: str) -> dict[str, Any]:
    """What `apply_checks` would write: empty commands filled, the test-runner switched on,
    `run_tests` after `implement` in CHECKED workflows that lack it; {} when nothing."""
    resolved = settings.load(paths, slug)
    changes: dict[str, Any] = {}
    if test and not resolved.project.test_cmd:
        changes["project.test_cmd"] = test
    if lint and not resolved.project.lint_cmd:
        changes["project.lint_cmd"] = lint
    has_checks = bool(changes or resolved.project.test_cmd or resolved.project.lint_cmd)
    runner = resolved.agents.get("test-runner")
    if not has_checks or runner is None:
        return changes
    if not runner.on:
        changes["agents.test-runner.on"] = True
    for name in CHECKED:
        flow = resolved.workflows.get(name)
        if flow is None or "run_tests" in flow.steps or "implement" not in flow.steps:
            continue
        steps = list(flow.steps)
        steps.insert(steps.index("implement") + 1, "run_tests")
        changes[f"workflows.{name}"] = {
            "steps": steps,
            "on_fail": {**flow.on_fail, "run_tests": "implement"},
        }
    return changes


def apply_checks(paths: StorePaths, slug: str, test: str, lint: str) -> list[str]:
    """Write `check_changes` in one validated save; the keys that changed."""
    changes = check_changes(paths, slug, test, lint)
    return configure.save_settings(changes, project=slug, by=BY).keys if changes else []


def old_defaults(paths: StorePaths, slug: str | None) -> list[str]:
    """Keys in one scope's own file that still hold an old package default."""
    own = settings.scope_layer(paths, slug)
    found: list[str] = []
    if (own.get("tokens") or {}).get("per_ticket_max") == OLD_TOKEN_CAP:
        found.append("tokens.per_ticket_max")
    if "fallback_on_rate_limit" in own:
        found.append("fallback_on_rate_limit")
    writer = (own.get("agents") or {}).get("doc-writer")
    if isinstance(writer, dict) and "fallback" not in writer:
        found.append("agents.doc-writer.fallback")
    return found


def fix_old_defaults(paths: StorePaths, slug: str | None) -> list[str]:
    """Replace exactly the old defaults of one scope, keeping its comments."""
    own = settings.scope_layer(paths, slug)
    changes: dict[str, Any] = {}
    for key in old_defaults(paths, slug):
        if key == "tokens.per_ticket_max":
            changes[key] = NEW_TOKEN_CAP
        elif key == "fallback_on_rate_limit":
            changes["fallback_on_error"] = bool(own["fallback_on_rate_limit"])
        else:
            changes[key] = FALLBACK
    return configure.save_settings(changes, project=slug, by=BY).keys if changes else []


def checks(paths: StorePaths, *, fix: bool) -> list[Note]:
    """Doctor's lines: projects without a test command or a checks step, old defaults,
    switched-on agents without a fallback (information)."""
    notes: list[Note] = []
    registry = load_registry(paths)
    for scope in [None, *sorted(registry.projects)]:
        name = scope or "defaults"
        stale = old_defaults(paths, scope)
        if stale and fix:
            fix_old_defaults(paths, scope)
            notes += [Note(f"{name}: {key} updated", scope, fixed=True) for key in stale]
        else:
            hint = "run: kengash doctor --fix"
            notes += [
                Note(f"{name} still has the old default {key}; {hint}", scope) for key in stale
            ]
    for slug, entry in sorted(registry.projects.items()):
        notes += _project(paths, slug, entry.path, fix)
    notes += _fallbacks(paths, registry.projects)
    return notes


def _project(paths: StorePaths, slug: str, repo: Path, fix: bool) -> list[Note]:
    try:
        resolved = settings.load(paths, slug)
    except KengashError:
        return []  # broken settings are reported elsewhere
    test, lint = detect_commands(repo) if repo.is_dir() else ("", "")
    if not resolved.project.test_cmd:
        if not test:
            message = f"project {slug} has no test command; set project.test_cmd"
            return [Note(message, slug, warning=False, info=True)]
        if fix:
            apply_checks(paths, slug, test, lint)
            return [Note(f"project {slug}: test command set to {test}", slug, fixed=True)]
        hint = "run: kengash doctor --fix"
        return [Note(f"project {slug} has no test command; detected: {test}; {hint}", slug)]
    if check_changes(paths, slug, "", ""):
        if fix:
            apply_checks(paths, slug, "", "")
            return [Note(f"project {slug}: checks step added", slug, fixed=True)]
        return [Note(f"project {slug} runs no checks step; run: kengash doctor --fix", slug)]
    return []


def _fallbacks(paths: StorePaths, registered: dict[str, Any]) -> list[Note]:
    """One information line per scope: switched-on agents without a fallback; a project
    names only those its own settings add to the defaults' list."""
    notes: list[Note] = []
    base: set[str] = set()
    for scope in [None, *sorted(registered)]:
        try:
            resolved = settings.load(paths, scope)
        except (KengashError, UserError):
            continue
        bare = {
            role
            for role, agent in resolved.agents.items()
            if agent.on and not agent.fallback and not agent.cli.startswith("shell")
        }
        shown = sorted(bare if scope is None else bare - base)
        if scope is None:
            base = bare
        if shown:
            message = f"{scope or 'defaults'}: agents without a fallback: {', '.join(shown)}"
            notes.append(Note(message, scope, warning=False, info=True))
    return notes
