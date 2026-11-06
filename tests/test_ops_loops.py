"""The loop use cases: the hand-off race and a side-effect-free queue (SP11 spec §4.6)."""

import os
from collections.abc import Callable

import pytest

from kengash_ai.model import Doc, LoopBusy, Ticket, UserError
from kengash_ai.ops import conductors, loops, queue
from kengash_ai.ops.conductors import Conductor, process_name
from kengash_ai.store import StorePaths, documents

A = Conductor(os.getpid(), "claude", process_name(os.getpid()) or "", True)
B = Conductor(os.getppid(), "codex", process_name(os.getppid()) or "", True)


@pytest.fixture
def as_conductor(monkeypatch: pytest.MonkeyPatch) -> Callable[[Conductor], None]:
    def use(who: Conductor) -> None:
        monkeypatch.setattr(conductors, "conductor", lambda: who)

    return use


@pytest.mark.usefixtures("registered_repo")
def test_the_hand_off_race_in_both_orders(
    as_conductor: Callable[[Conductor], None],
    store_paths: StorePaths,
    make_ticket: Callable[..., Doc[Ticket]],
) -> None:
    # order 1: B adds a ready ticket while A still loops; B is told A runs; A cannot end
    as_conductor(A)
    loops.claim("payments-api")
    documents.save_ticket(store_paths.project("payments-api"), make_ticket())
    as_conductor(B)
    with pytest.raises(LoopBusy):
        loops.claim("payments-api")
    as_conductor(A)
    with pytest.raises(UserError, match="not released: 1 runnable"):
        loops.release()
    # order 2: A ends first (nothing runnable), then B claims
    loops.release(force=True)
    loops.claim("payments-api")
    ticket = documents.find_ticket(store_paths.project("payments-api"), "7b55e0c1")
    assert ticket is not None
    ticket.unlink()
    assert loops.release().scope == "payments-api"
    as_conductor(B)
    assert loops.claim("payments-api").new


@pytest.mark.usefixtures("registered_repo")
def test_compute_has_no_side_effects(
    store_paths: StorePaths, make_ticket: Callable[..., Doc[Ticket]]
) -> None:
    documents.save_ticket(store_paths.project("payments-api"), make_ticket())
    found = queue.compute(store_paths, "payments-api")
    assert [item.id for item in found.runnable] == ["7b55e0c1"]
    assert not store_paths.conductors.exists()
