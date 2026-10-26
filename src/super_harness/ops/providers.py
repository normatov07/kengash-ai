"""Provider and repo-trust checks for `harness doctor` (SP3 spec §10)."""

import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from super_harness import adapters, settings
from super_harness.model import PROVIDERS, ProviderStatus, Settings, UserError, split_cli
from super_harness.store import runtime
from super_harness.store.paths import StorePaths
from super_harness.store.registry import load_registry

SUBSCRIPTION = "claude.ai"


@dataclass
class ProviderCheck:
    provider: str
    users: list[str]
    blocking: bool
    message: str


@dataclass(frozen=True)
class _Use:
    """Who needs a provider: a role or the compactor, with its providers in fallback order."""

    label: str
    chain: tuple[str, ...]


def check_providers(paths: StorePaths) -> list[ProviderCheck]:
    """Providers that enabled agents or the compactor need and cannot use as things stand.

    Scopes whose SETTINGS.md does not validate are skipped; `harness settings check`
    reports them.
    """
    scopes: list[Settings] = []
    for slug in [None, *sorted(load_registry(paths).projects)]:
        try:
            scopes.append(settings.load(paths, slug))
        except UserError:
            continue
    if not scopes:
        return []
    uses = [use for scope in scopes for use in _uses(scope)]
    statuses = {
        name: _detect(paths, name) for name in PROVIDERS if any(name in use.chain for use in uses)
    }
    checks: list[ProviderCheck] = []
    for name, status in statuses.items():
        users = list(dict.fromkeys(use.label for use in uses if name in use.chain))
        used_by = ", ".join(users)
        if not status.installed:
            message = f"{name}: not installed; used by {used_by}; {status.hint}"
        elif not status.signed_in:
            message = f"{name}: signed out; used by {used_by}; {status.hint}"
        else:
            method = status.auth_method
            billed = name == "claude" and method not in (None, SUBSCRIPTION)
            if billed and not scopes[0].provider("claude").allow_api_key:
                message = (
                    f"claude: signed in with {method}, not a claude.ai subscription; "
                    "workers will bill it"
                )
                checks.append(ProviderCheck(name, users, False, message))
            continue
        stuck = [
            use
            for use in uses
            if use.chain[0] == name and not any(statuses[p].usable for p in use.chain)
        ]
        checks.append(ProviderCheck(name, users, bool(stuck), message))
    return checks


def cli_clash() -> str | None:
    """A warning when the first `harness` on PATH is another tool (system spec §12): skills
    then need `--cli-name hrn`. None when it is super-harness's own, or there is none."""
    found = shutil.which("harness")
    if found is None:
        return None
    if Path(found).resolve().parent == Path(sys.executable).resolve().parent:
        return None  # the environment running this harness: ours
    try:
        result = subprocess.run(
            [found, "--version"], capture_output=True, text=True, timeout=10, check=False
        )
        output = result.stdout
    except (OSError, subprocess.TimeoutExpired):
        output = ""
    if output.startswith("super-harness "):
        return None
    return (
        f"the first harness on PATH ({found}) is not super-harness; "
        "run hrn instead, and install skills with --cli-name hrn"
    )


def trust_notice(paths: StorePaths, slug: str, repo: Path) -> str | None:
    """A warning when the repo ships agent hooks or MCP config; once until those files change."""
    found: list[str] = []
    contents: list[bytes] = []
    claude_settings = repo / ".claude" / "settings.json"
    if claude_settings.is_file():
        raw = claude_settings.read_bytes()
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
        if isinstance(data, dict) and data.get("hooks"):
            found.append(".claude/settings.json hooks")
            contents.append(raw)
    mcp = repo / ".mcp.json"
    if mcp.is_file():
        found.append(".mcp.json")
        contents.append(mcp.read_bytes())
    trust = runtime.load_trust(paths)
    if not found:
        if trust.seen.pop(slug, None) is not None:
            runtime.save_trust(paths, trust)
        return None
    digest = hashlib.sha256(b"".join(contents)).hexdigest()
    if trust.seen.get(slug) == digest:
        return None
    trust.seen[slug] = digest
    runtime.save_trust(paths, trust)
    return f"repo ships {' and '.join(found)}; workers run them without a trust prompt"


def _uses(scope: Settings) -> list[_Use]:
    uses = [
        _Use(role, tuple(split_cli(cli)[0] for cli in (agent.cli, *agent.fallback)))
        for role, agent in scope.agents.items()
        if agent.on and split_cli(agent.cli)[0] != "shell"
    ]
    uses.append(_Use("compactor", (split_cli(scope.memory.compactor)[0],)))
    return uses


def _detect(paths: StorePaths, name: str) -> ProviderStatus:
    return adapters.get(name, runtime=paths.runtime).detect()
