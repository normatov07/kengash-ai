"""Claims that follow the edits, and stuck tickets said out loud (SP18 spec §3.7, §3.8)."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from kengash_ai import gitops, scheduler, settings
from kengash_ai.cli import app
from kengash_ai.model import Doc, Ticket
from kengash_ai.ops import queue, steps, watch
from kengash_ai.store import StorePaths, documents

runner = CliRunner()
Make = Callable[..., Doc[Ticket]]
POLICY = scheduler.PathPolicy(("*.g.dart",), 0)
FAILED = {"status": "in_process/failed", "step": "implement"}


def behind(make: Make, *ids: str) -> dict[str, Doc[Ticket]]:
    root = make("7b55e0c1", **FAILED)
    docs = {root.meta.id: root}
    for ticket_id in ids:
        docs[ticket_id] = make(ticket_id, status="in_queue/blocked", depends_on=["7b55e0c1"])
    return docs


def test_needs_claim() -> None:
    assert scheduler.needs_claim("lib/b.dart", ["lib/a.dart"], POLICY)
    assert not scheduler.needs_claim("lib/a.dart", ["lib/a.dart"], POLICY)
    assert not scheduler.needs_claim("lib/x/b.dart", ["lib/x/"], POLICY)
    assert not scheduler.needs_claim("lib/a.g.dart", ["src/"], POLICY)


def test_failed_ticket_holding_three_is_listed(make_ticket: Make) -> None:
    (found,) = queue.stuck(behind(make_ticket, "a0000001", "a0000002", "a0000003"), "app")
    assert (found.id, found.status, found.behind) == ("7b55e0c1", "in_process/failed", 3)


def test_two_behind_is_not_listed(make_ticket: Make) -> None:
    assert queue.stuck(behind(make_ticket, "a0000001", "a0000002"), "app") == []


def test_chain_counts_transitively(make_ticket: Make) -> None:
    docs = behind(make_ticket, "a0000001")
    docs["a0000002"] = make_ticket("a0000002", status="in_queue/blocked", depends_on=["a0000001"])
    docs["a0000003"] = make_ticket("a0000003", status="in_queue/blocked", depends_on=["a0000002"])
    assert queue.stuck(docs, "app")[0].behind == 3


def test_parked_ticket_counts_running_does_not(make_ticket: Make) -> None:
    docs = behind(make_ticket, "a0000001", "a0000002", "a0000003")
    docs["7b55e0c1"] = make_ticket(status="in_queue/parked")
    assert queue.stuck(docs, "app")[0].status == "in_queue/parked"
    docs["7b55e0c1"] = make_ticket(status="in_process/implementing", step="implement")
    assert queue.stuck(docs, "app") == []


def test_finished_dependents_do_not_count(make_ticket: Make) -> None:
    docs = behind(make_ticket, "a0000001", "a0000002", "a0000003")
    docs["a0000003"] = make_ticket(
        "a0000003", status="done/merged", depends_on=["7b55e0c1"], step=None
    )
    assert queue.stuck(docs, "app") == []


def test_next_prints_waiting_on(
    inside_registered_repo: Path, store_paths: StorePaths, make_ticket: Make
) -> None:
    project = store_paths.project("payments-api")
    for doc in behind(make_ticket, "a0000001", "a0000002", "a0000003").values():
        documents.save_ticket(project, doc)
    out = runner.invoke(app, ["next"]).stdout
    assert "waiting on 7b55e0c1 (in_process/failed): 3 tickets behind it" in out


def test_watch_prints_waiting_on(
    inside_registered_repo: Path, store_paths: StorePaths, make_ticket: Make
) -> None:
    project = store_paths.project("payments-api")
    for doc in behind(make_ticket, "a0000001", "a0000002", "a0000003").values():
        documents.save_ticket(project, doc)
    out = watch.lines(watch.board(store_paths, ["payments-api"]))
    assert "waiting on 7b55e0c1 (in_process/failed): 3 tickets behind it" in out


def test_edit_outside_touches_joins_claim(engine: Any, fake_clis: Any, journal_events: Any) -> None:
    claimed = _run_edit(engine, fake_clis, ["services/webhooks"], "lib/extra.py")
    assert "lib/extra.py" in claimed.meta.touches
    assert "claimed 1 more files" in claimed.sections["Log"]


def test_shared_files_stay_unclaimed(engine: Any, fake_clis: Any) -> None:
    claimed = _run_edit(engine, fake_clis, ["services/webhooks"], "gen/out.g.dart")
    assert claimed.meta.touches == ["services/webhooks"]


def test_whole_repo_claim_unchanged(engine: Any, fake_clis: Any) -> None:
    claimed = _run_edit(engine, fake_clis, [], "lib/extra.py")
    assert claimed.meta.touches == []


def test_new_clash_is_journaled(
    engine: Any, fake_clis: Any, journal_events: Any, make_ticket: Make, store_paths: StorePaths
) -> None:
    other = make_ticket(
        "a0000001", status="in_process/implementing", step="implement", touches=["lib/extra.py"]
    )
    documents.save_ticket(store_paths.project("payments-api"), other)
    settings.set_values(store_paths, "payments-api", {"paths.max_overlap": 0})
    claimed = _run_edit(engine, fake_clis, ["services/webhooks"], "lib/extra.py")
    assert "overlaps a0000001" in claimed.sections["Log"]
    event = next(e for e in journal_events() if e["type"] == "ticket.overlap")
    assert event["holder"] == "a0000001" and event["files"] == ["lib/extra.py"]


def _run_edit(engine: Any, clis: Any, touches: list[str], edited: str) -> Doc[Ticket]:
    doc = engine.ticket()
    doc.meta.touches = touches
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    clis.queue("claude", fixture="claude/work_resume.json")
    clis.queue("codex", fixture="codex/work_resume.jsonl", edits={edited: "x = 1\n"})
    steps.run_job("7b55e0c1", steps=2)
    done: Doc[Ticket] = engine.ticket()
    return done


def test_branch_files_lists_both_names_of_a_rename(
    repo: Path, run_git: Callable[..., str], tmp_path: Path, monkeypatch: Any
) -> None:
    config = tmp_path / "gitconfig"
    config.write_text("[user]\n\tname = Dev\n\temail = dev@example.com\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    (repo / "old.py").write_text("x = 1\n" * 20, encoding="utf-8")
    run_git(repo, "add", "old.py")
    run_git(repo, "commit", "-m", "seed")
    base = run_git(repo, "rev-parse", "HEAD").strip()
    run_git(repo, "mv", "old.py", "new.py")
    run_git(repo, "commit", "-m", "move")
    assert set(gitops.branch_files(repo, base)) == {"old.py", "new.py"}
