"""Provider adapters: one driver per CLI behind the `Provider` protocol (SP3 spec §8)."""

from pathlib import Path

from kengash_ai.adapters.antigravity import Antigravity
from kengash_ai.adapters.base import Provider
from kengash_ai.adapters.claude import Claude
from kengash_ai.adapters.codex import Codex
from kengash_ai.adapters.shell import Shell
from kengash_ai.model import REPLACED, UserError, replaced

__all__ = ["Provider", "get", "known_models"]


def get(name: str, *, runtime: Path) -> Provider:
    """The driver for a provider (or `shell`); `runtime` holds files a CLI needs on disk."""
    if name == "claude":
        return Claude()
    if name == "codex":
        return Codex(runtime / "schemas")
    if name == "antigravity":
        return Antigravity()
    if name == "shell":
        return Shell()
    if name in REPLACED:
        raise UserError(replaced(name))
    raise UserError(f"unknown provider: {name}")


def known_models(name: str) -> list[str]:
    """The model names a CLI is known to take without asking it: Claude Code's aliases;
    none for CLIs whose list comes from the CLI itself or that have no list."""
    return list(Claude.MODELS) if name == "claude" else []
