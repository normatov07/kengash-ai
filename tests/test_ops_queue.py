from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from kengash_ai.model import Claims, Doc, SlotEntry, SlotTable, Ticket
from kengash_ai.ops import projects, queue
from kengash_ai.store import StorePaths, documents, runtime

NOW = datetime(2026, 10, 22, 9, 41, tzinfo=UTC)
Make = Callable[..., Doc[Ticket]]


def add_web_project(tmp_path: Path, run_git: Callable[..., str]) -> None:
    path = tmp_path / "code" / "web"
    path.mkdir(parents=True)
    run_git(path, "init", "-q", "-b", "main")
    run_git(path, "commit", "-q", "--allow-empty", "-m", "init")
    projects.init_project(path)


def test_projects_take_turns(
    store_paths: StorePaths,
    registered_repo: Path,
    tmp_path: Path,
    run_git: Callable[..., str],
    make_ticket: Make,
) -> None:
    add_web_project(tmp_path, run_git)
    payments = store_paths.project("payments-api")
    documents.save_ticket(payments, make_ticket(touches=["a"]))
    documents.save_ticket(payments, make_ticket("a91b3d07", touches=["b"]))
    simple = make_ticket("3c9d0e11", project="web", importance="simple", workflow="simple")
    documents.save_ticket(store_paths.project("web"), simple)
    runtime.save_claims(store_paths, Claims(last={"payments-api": NOW}))
    found = queue.next_tickets()
    assert [(t.id, t.project, t.step, t.provider) for t in found.runnable] == [
        ("3c9d0e11", "web", "plan", "claude"),
        ("7b55e0c1", "payments-api", "plan", "claude"),
        ("a91b3d07", "payments-api", "plan", "claude"),
    ]
    assert [t.id for t in queue.next_tickets("payments-api").runnable] == ["7b55e0c1", "a91b3d07"]


def test_slots_pauses_and_settings_hold_tickets_back(
    store_paths: StorePaths, registered_repo: Path, make_ticket: Make
) -> None:
    project = store_paths.project("payments-api")
    documents.save_ticket(project, make_ticket(touches=["a"]))
    documents.save_ticket(project, make_ticket("a91b3d07", touches=["b"], workflow="nope"))
    held = [
        SlotEntry(provider="claude", project="other", ticket=f"0000000{n}", step="plan", pid=n)
        for n in range(3)
    ]
    runtime.save_slots(store_paths, SlotTable(held=held))
    found = queue.next_tickets()
    assert found.runnable == []
    assert found.held_back == {
        "7b55e0c1": "no free claude slot",
        "a91b3d07": "settings have no workflow 'nope'",
    }
    runtime.set_pause(store_paths, "payments-api", on=True)
    assert queue.next_tickets().held_back == {"7b55e0c1": "paused", "a91b3d07": "paused"}
    runtime.set_pause(store_paths, "payments-api", on=False)
    runtime.save_slots(store_paths, SlotTable())
    text = project.settings.read_text(encoding="utf-8")
    off = text.replace("security-reviewer: {on: true,", "security-reviewer: {on: false,")
    project.settings.write_text(off, encoding="utf-8")
    held_back = queue.next_tickets().held_back
    assert held_back["7b55e0c1"] == "role security-reviewer is off and blocking"
