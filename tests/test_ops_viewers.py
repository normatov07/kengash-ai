"""One viewer tab per key (SP13 spec §3.1)."""

import os
import subprocess
import sys
from datetime import timedelta

from kengash_ai.model import ViewerRecord, utc_now
from kengash_ai.ops import viewers
from kengash_ai.store import StorePaths, runtime


def _dead_pid() -> int:
    argv = [sys.executable, "-c", "import os; print(os.getpid())"]
    done = subprocess.run(argv, check=True, capture_output=True, text=True)
    return int(done.stdout)


def test_a_key_is_claimed_once(store_paths: StorePaths) -> None:
    assert viewers.claim(store_paths, "ticket-7add8c2e") is True
    assert viewers.claim(store_paths, "ticket-7add8c2e") is False  # the tab is opening
    assert viewers.claim(store_paths, "ticket-0b1c2d3e") is True


def test_a_registered_viewer_holds_its_key_until_it_ends(store_paths: StorePaths) -> None:
    viewers.register(store_paths, "ticket-7add8c2e")
    assert viewers.live(store_paths, "ticket-7add8c2e")
    assert viewers.claim(store_paths, "ticket-7add8c2e") is False
    viewers.release(store_paths, "ticket-7add8c2e")
    assert not viewers.live(store_paths, "ticket-7add8c2e")
    assert viewers.claim(store_paths, "ticket-7add8c2e") is True


def test_a_dead_viewer_or_an_old_claim_frees_the_key(store_paths: StorePaths) -> None:
    runtime.save_viewer(store_paths, ViewerRecord(key="ticket-a", pid=_dead_pid()))
    assert viewers.claim(store_paths, "ticket-a") is True
    old = utc_now() - timedelta(seconds=viewers.CLAIM_S + 1)
    runtime.save_viewer(store_paths, ViewerRecord(key="ticket-b", pid=None, since=old))
    assert viewers.claim(store_paths, "ticket-b") is True


def test_release_keeps_another_viewers_record(store_paths: StorePaths) -> None:
    runtime.save_viewer(store_paths, ViewerRecord(key="watch-all", pid=os.getppid()))
    viewers.release(store_paths, "watch-all")
    assert viewers.live(store_paths, "watch-all")
