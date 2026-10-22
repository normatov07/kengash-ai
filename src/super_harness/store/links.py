"""The per-repo `.harness` directory symlink into the store (system spec §4.2)."""

import os
import subprocess
from enum import StrEnum
from pathlib import Path

LINK = ".harness"
EXCLUDE_ENTRY = "/.harness"


class LinkState(StrEnum):
    ok = "ok"
    missing = "missing"
    wrong = "points elsewhere"
    real_dir = "real folder"
    blocked = "blocked by a file"


def obstruction(repo: Path) -> LinkState | None:
    """`real_dir` or `blocked` when something other than a symlink sits at `.harness`."""
    link = repo / LINK
    if link.is_symlink() or not link.exists():
        return None
    return LinkState.real_dir if link.is_dir() else LinkState.blocked


def link_state(repo: Path, target: Path) -> LinkState:
    link = repo / LINK
    if link.is_symlink():
        return LinkState.ok if Path(os.readlink(link)) == target else LinkState.wrong
    return obstruction(repo) or LinkState.missing


def make_link(repo: Path, target: Path) -> None:
    """Point `<repo>/.harness` at `target`, replacing a stale symlink."""
    link = repo / LINK
    if link.is_symlink():
        link.unlink()
    link.symlink_to(target, target_is_directory=True)


def _exclude_file(repo: Path) -> Path | None:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "rev-parse",
            "--path-format=absolute",
            "--git-path",
            "info/exclude",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return Path(result.stdout.strip()) if result.returncode == 0 else None


def is_excluded(repo: Path) -> bool | None:
    """Whether info/exclude lists `/.harness`; None when `repo` is not a git work tree."""
    path = _exclude_file(repo)
    if path is None:
        return None
    return path.exists() and EXCLUDE_ENTRY in path.read_text(encoding="utf-8").splitlines()


def ensure_excluded(repo: Path) -> bool:
    """Add `/.harness` to info/exclude once; False when `repo` is not a git work tree."""
    path = _exclude_file(repo)
    if path is None:
        return False
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    if EXCLUDE_ENTRY not in lines:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join([*lines, EXCLUDE_ENTRY]) + "\n", encoding="utf-8")
    return True
