"""The per-repo `.kengash` directory symlink into the store (system spec §4.2); 0.1.0 named
it `.harness` (SP8 spec decision 3)."""

import os
import subprocess
from enum import StrEnum
from pathlib import Path

LINK = ".kengash"
LEGACY_LINK = ".harness"
EXCLUDE_ENTRY = "/.kengash"


class LinkState(StrEnum):
    ok = "ok"
    missing = "missing"
    wrong = "points elsewhere"
    real_dir = "real folder"
    blocked = "blocked by a file"


def obstruction(repo: Path) -> LinkState | None:
    """`real_dir` or `blocked` when something other than a symlink sits at `.kengash`."""
    return _obstruction(repo / LINK)


def link_state(repo: Path, target: Path) -> LinkState:
    """The state of the repo's folder link to `target`."""
    return state_of(repo / LINK, target)


def state_of(link: Path, target: Path) -> LinkState:
    """The state of any folder link: `ok` when it is a symlink that reaches `target`."""
    if link.is_symlink():
        same = Path(os.readlink(link)) == target or link.resolve() == target.resolve()
        return LinkState.ok if same else LinkState.wrong
    return _obstruction(link) or LinkState.missing


def _obstruction(link: Path) -> LinkState | None:
    if link.is_symlink() or not link.exists():
        return None
    return LinkState.real_dir if link.is_dir() else LinkState.blocked


def real_folder(repo: Path) -> Path | None:
    """A real `.kengash/` folder in `repo`, else a real 0.1.0 `.harness/` one, else None."""
    for name in (LINK, LEGACY_LINK):
        candidate = repo / name
        if candidate.is_dir() and not candidate.is_symlink():
            return candidate
    return None


def legacy_link(repo: Path, target: Path) -> Path | None:
    """`<repo>/.harness` when it is a 0.1.0 symlink to `target`; a link elsewhere is not ours."""
    link = repo / LEGACY_LINK
    if link.is_symlink() and link.resolve() == target.resolve():
        return link
    return None


def make_link(repo: Path, target: Path) -> None:
    """Point `<repo>/.kengash` at `target`, replacing a stale symlink."""
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
    """Whether info/exclude lists `/.kengash`; None when `repo` is not a git work tree."""
    path = _exclude_file(repo)
    if path is None:
        return None
    return path.exists() and EXCLUDE_ENTRY in path.read_text(encoding="utf-8").splitlines()


def ensure_excluded(repo: Path) -> bool:
    """Add `/.kengash` to info/exclude once; False when `repo` is not a git work tree."""
    path = _exclude_file(repo)
    if path is None:
        return False
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    if EXCLUDE_ENTRY not in lines:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join([*lines, EXCLUDE_ENTRY]) + "\n", encoding="utf-8")
    return True
