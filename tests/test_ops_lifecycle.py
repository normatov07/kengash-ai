"""Which tickets hold their paths (SP16 spec §3.7)."""

from collections.abc import Callable

import pytest

from kengash_ai import settings
from kengash_ai.model import Doc, Ticket
from kengash_ai.ops import lifecycle
from kengash_ai.store import StorePaths
from kengash_ai.store.seed import ensure_store

Make = Callable[..., Doc[Ticket]]


@pytest.mark.parametrize(
    ("status", "step", "holds"),
    [
        ("in_process/under_planning", "plan", False),  # planning edits nothing
        ("in_process/waiting_slot", "plan", False),
        ("in_process/under_implementation", "implement", True),
        ("in_process/waiting_slot", "implement", True),
        ("in_process/under_review", "review_code", True),
        ("in_process/awaiting_merge", None, True),  # its edits wait to land
        ("in_process/needs_approval", "implement", False),  # gates let go
        ("in_process/failed", "implement", False),
        ("in_process/stalled", "review_code", False),
        ("in_process/paused", "implement", False),
        ("in_process/waiting_paths", "implement", False),
        ("in_queue/ready", "implement", False),
        ("done/merged", None, False),
    ],
)
def test_holds_paths(
    store_paths: StorePaths, make_ticket: Make, status: str, step: str | None, holds: bool
) -> None:
    ensure_store(store_paths)
    resolved = settings.load(store_paths)
    ticket = make_ticket(status=status, step=step, workflow="standard").meta
    assert lifecycle.holds_paths(resolved, ticket) is holds
