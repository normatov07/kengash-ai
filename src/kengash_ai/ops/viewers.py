"""One viewer tab per key (SP13 spec §3.1): a viewer registers its pid under
runtime/viewers/<key>.json while it runs; an opener claims the key for CLAIM_S seconds
while the tab starts, so two quick starts never open two tabs."""

import os

from kengash_ai.model import ViewerRecord, utc_now
from kengash_ai.ops import lifecycle
from kengash_ai.store import runtime
from kengash_ai.store.locks import locked
from kengash_ai.store.paths import StorePaths

CLAIM_S = 15  # how long an opening tab holds its key before its viewer registers


def claim(paths: StorePaths, key: str) -> bool:
    """Hold `key` for a tab about to open; False while a viewer or another claim holds it."""
    with locked(paths.locks / "viewers.lock"):
        if _held(runtime.load_viewer(paths, key)):
            return False
        runtime.save_viewer(paths, ViewerRecord(key=key))
        return True


def register(paths: StorePaths, key: str) -> None:
    """This process is the viewer of `key`."""
    with locked(paths.locks / "viewers.lock"):
        runtime.save_viewer(paths, ViewerRecord(key=key, pid=os.getpid()))


def release(paths: StorePaths, key: str) -> None:
    """Drop `key`'s record when this process holds it; another viewer's stays."""
    with locked(paths.locks / "viewers.lock"):
        record = runtime.load_viewer(paths, key)
        if record is not None and record.pid == os.getpid():
            runtime.drop_viewer(paths, key)


def unclaim(paths: StorePaths, key: str) -> None:
    """Free a claim whose tab did not open."""
    with locked(paths.locks / "viewers.lock"):
        record = runtime.load_viewer(paths, key)
        if record is not None and record.pid is None:
            runtime.drop_viewer(paths, key)


def live(paths: StorePaths, key: str) -> bool:
    """A viewer process runs for `key`."""
    record = runtime.load_viewer(paths, key)
    return record is not None and record.pid is not None and lifecycle.pid_alive(record.pid)


def _held(record: ViewerRecord | None) -> bool:
    if record is None:
        return False
    if record.pid is not None:
        return lifecycle.pid_alive(record.pid)
    return (utc_now() - record.since).total_seconds() < CLAIM_S
