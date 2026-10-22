from collections.abc import Callable
from pathlib import Path

import pytest

from super_harness.model import Doc, Ticket, UserError
from super_harness.ops import status
from super_harness.ops.workspace import OpenGate
from super_harness.store import StorePaths, documents


def test_board_counts_folders_and_lists_gates(
    store_paths: StorePaths, registered_repo: Path, make_ticket: Callable[..., Doc[Ticket]]
) -> None:
    project = store_paths.project("payments-api")
    documents.save_ticket(project, make_ticket(status="in_process/needs_approval"))
    documents.save_ticket(project, make_ticket("a91b3d07", status="in_queue/ready"))
    documents.save_ticket(project, make_ticket("3c9d0e11", status="done/merged"))
    [item] = status.board().projects
    assert item.folders == {"in_queue": 1, "in_process": 1, "done": 1}
    assert item.statuses == {
        "done/merged": 1,
        "in_process/needs_approval": 1,
        "in_queue/ready": 1,
    }
    assert item.gates == [OpenGate("7b55e0c1", "needs_approval", "Rotate keys")]


def test_board_of_an_empty_store(store_paths: StorePaths) -> None:
    assert status.board().projects == []
    with pytest.raises(UserError, match="unknown project: nope"):
        status.board("nope")
