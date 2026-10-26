"""The one-time move of a 0.1.0 store, ~/.harness, to ~/.kengash (SP8 spec decision 2).

It follows the tested rename recipe: move only a plain old directory into an absent new one,
leave the old path as a link so running workers, older binaries, project links and git
worktree records keep resolving, never merge two real directories, never move a location an
environment variable chose.
"""

import os
from pathlib import Path

from kengash_ai.store.paths import ENV_HOME, HOME_NAME, LEGACY_ENV_HOME, LEGACY_HOME_NAME


def legacy_home() -> str | None:
    """Move ~/.kengash to ~/.kengash once and link the old path to it; a one-line note when
    it moved, else None (nothing to move, a custom location, or both exist)."""
    if os.environ.get(ENV_HOME) or os.environ.get(LEGACY_ENV_HOME):
        return None
    old, new = Path.home() / LEGACY_HOME_NAME, Path.home() / HOME_NAME
    if new.exists() or new.is_symlink() or old.is_symlink() or not old.is_dir():
        return None  # doctor reports a leftover ~/.kengash beside ~/.kengash
    old.rename(new)
    old.symlink_to(HOME_NAME)  # relative: the link survives the home folder moving
    return f"moved {old} to {new}; {old} now links to it"
