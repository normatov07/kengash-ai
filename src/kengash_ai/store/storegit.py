"""The store's own git history: every state change becomes a commit (system spec §4.3)."""

import subprocess
from pathlib import Path

from kengash_ai.model import HarnessError
from kengash_ai.store.locks import locked
from kengash_ai.store.paths import StorePaths

IDENTITY = (
    "-c",
    "user.name=harness",
    "-c",
    "user.email=harness@localhost",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "core.hooksPath=/dev/null",
)
IGNORED = "runtime/\nworktrees/\n"


def _git(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *IDENTITY, *args], cwd=home, capture_output=True, text=True, check=False
    )


def ensure_repo(home: Path) -> None:
    """Make `home` a git repo that ignores runtime state and worktrees."""
    if not (home / ".git").exists():
        result = _git(home, "init", "-q", "-b", "main")
        if result.returncode != 0:
            raise HarnessError(f"store git init failed: {result.stderr.strip()}")
    ignore = home / ".gitignore"
    if not ignore.exists():
        ignore.write_text(IGNORED, encoding="utf-8")


def commit(home: Path, message: str) -> bool:
    """Commit every change under `home`; False when there was nothing to commit."""
    _git(home, "add", "-A")
    if _git(home, "diff", "--cached", "--quiet").returncode == 0:
        return False
    result = _git(home, "commit", "-q", "-m", message)
    if result.returncode != 0:
        raise HarnessError(f"store commit failed: {result.stderr.strip()}")
    return True


def commit_store(paths: StorePaths, message: str) -> bool:
    """Commit the store under its git lock, so concurrent commands never collide."""
    with locked(paths.locks / "git.lock"):
        return commit(paths.home, message)
