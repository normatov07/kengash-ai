"""Provider adapters: one driver per CLI behind the `Provider` protocol (SP3 spec §8)."""

from pathlib import Path

from super_harness.adapters.antigravity import Antigravity
from super_harness.adapters.base import Provider
from super_harness.adapters.claude import Claude
from super_harness.adapters.codex import Codex
from super_harness.adapters.shell import Shell
from super_harness.model import NeedsSetup, UserError

__all__ = ["Provider", "get"]


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
    if name == "gemini":
        raise NeedsSetup("gemini is not supported yet; pick another provider in SETTINGS.md")
    raise UserError(f"unknown provider: {name}")
