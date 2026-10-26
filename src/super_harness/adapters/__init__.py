"""Provider adapters: one driver per CLI behind the `Provider` protocol (SP3 spec §8)."""

from pathlib import Path

from super_harness.adapters.antigravity import Antigravity
from super_harness.adapters.base import Provider
from super_harness.adapters.claude import Claude
from super_harness.adapters.codex import Codex
from super_harness.adapters.shell import Shell
from super_harness.model import NeedsSetup, UserError

__all__ = ["Provider", "get"]


# Providers harness knows by name but cannot drive, and why (SP6 spec decision 9)
UNSUPPORTED = {
    "gemini": "Google moved Gemini CLI's Pro, Ultra and free plans to Antigravity CLI on "
    "2026-06-18 and harness never uses API keys; pick antigravity in SETTINGS.md",
}


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
    if name in UNSUPPORTED:
        raise NeedsSetup(f"{name} is not supported: {UNSUPPORTED[name]}")
    raise UserError(f"unknown provider: {name}")
