"""Merge: rebase onto the base branch, fast-forward, clean up (SP3 spec §9, decision 23)."""

import threading
import time
from collections.abc import Callable

import pytest
from conftest import Engine, Events, write_settings

from kengash_ai import gitops
from kengash_ai.model import Checked, Doc, Ticket, TicketState, UserError
from kengash_ai.ops import changes, checks, merging, records
from kengash_ai.ops.merging import Merged
from kengash_ai.store import documents, runtime
from kengash_ai.store.locks import locked

Make = Callable[..., Doc[Ticket]]


def ready_to_merge(engine: Engine, run_git: Callable[..., str]) -> None:
    (engine.worktree / "retry.py").write_text("retries = 3\n")
    gitops.commit_all(
        engine.worktree,
        "hrn(7b55e0c1): loop 1 implement: retry",
        {"Harness-Ticket": str(engine.ticket().meta.uuid)},
    )
    doc = engine.ticket()
    doc.meta.status, doc.meta.step = "in_process/awaiting_merge", None
    documents.save_ticket(engine.paths.project(engine.slug), doc)


def test_merge_fast_forwards_and_unblocks_dependents(
    engine: Engine, make_ticket: Make, run_git: Callable[..., str]
) -> None:
    ready_to_merge(engine, run_git)
    dependent = make_ticket("a91b3d07", status="in_queue/blocked", depends_on=["7b55e0c1"])
    documents.save_ticket(engine.paths.project(engine.slug), dependent)
    assert merging.merge_ticket("7b55e0c1", project=None, by="user") == Merged(
        "7b55e0c1", "payments-api", 1, "main"
    )
    assert engine.ticket().meta.status == "done/merged" and not engine.worktree.exists()
    assert (engine.repo / "retry.py").exists()
    dependent_path = documents.find_ticket(engine.paths.project(engine.slug), "a91b3d07")
    assert dependent_path is not None
    assert records.load_ticket(dependent_path).meta.status == "in_queue/ready"


def test_a_conflict_sends_the_ticket_back(engine: Engine, run_git: Callable[..., str]) -> None:
    (engine.worktree / "README.md").write_text("ticket\n")
    gitops.commit_all(engine.worktree, "edit readme", {})
    (engine.repo / "README.md").write_text("main\n")
    gitops.commit_all(engine.repo, "main edit", {})
    doc = engine.ticket()
    doc.meta.status, doc.meta.step = "in_process/awaiting_merge", None
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    with pytest.raises(
        UserError, match=r"conflict in README.md; 7b55e0c1 sent back to implement \(loop 2\)"
    ):
        merging.merge_ticket("7b55e0c1", project=None, by="user")
    after = engine.ticket()
    assert (after.meta.status, after.meta.step, after.meta.loop) == (
        "in_queue/ready",
        "implement",
        2,
    )
    assert "README.md:0 · rebase onto main conflicts" in after.sections["Findings"]


def test_merge_refuses_other_states_and_a_dirty_tree(
    engine: Engine, run_git: Callable[..., str]
) -> None:
    with pytest.raises(UserError, match="merge needs awaiting_merge or branch_ready"):
        merging.merge_ticket("7b55e0c1", project=None, by="user")
    ready_to_merge(engine, run_git)
    (engine.repo / "README.md").write_text("dirty\n")
    with pytest.raises(UserError, match="main working tree has uncommitted changes"):
        merging.merge_ticket("7b55e0c1", project=None, by="user")
    assert (
        merging.merge_if_clean(engine.paths, engine.slug, "7b55e0c1", by="kengash")
        == "in_process/awaiting_merge"
    )


def test_a_ticket_claimed_before_0_2_shows_its_changes_and_merges(
    engine: Engine, run_git: Callable[..., str]
) -> None:
    """A 0.1.0 claim: branch hrn/<id>, worktree hrn-<id>, Harness-* trailers."""
    gitops.remove_worktree(engine.repo, engine.worktree, "kg/7b55e0c1")
    legacy = engine.paths.worktrees / engine.slug / "hrn-7b55e0c1"
    gitops.ensure_worktree(engine.repo, legacy, "hrn/7b55e0c1", "main")
    doc = engine.ticket()
    doc.meta.branch = "hrn/7b55e0c1"
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    assert engine.paths.worktree(engine.slug, "7b55e0c1") == legacy
    (legacy / "retry.py").write_text("retries = 3\n")
    trailers = {"Harness-Ticket": str(doc.meta.uuid), "Harness-Model": "codex/default"}
    gitops.commit_all(legacy, "hrn(7b55e0c1): loop 1 implement: retry", trailers)
    [change] = changes.ticket_changes("7b55e0c1", diff=False, project=None).changes
    assert (change.path, change.model) == ("retry.py", "codex/default")
    doc = engine.ticket()
    doc.meta.status, doc.meta.step = "in_process/awaiting_merge", None
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    assert merging.merge_ticket("7b55e0c1", project=None, by="user").commits == 1
    assert not legacy.exists() and (engine.repo / "retry.py").exists()


def test_merge_records_ticket_decisions(engine: Engine, run_git: Callable[..., str]) -> None:
    ready_to_merge(engine, run_git)
    doc = engine.ticket()
    doc.sections["Decisions"] = "- retries use full jitter. why: herd. rejected: fixed delay."
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    merged = merging.merge_ticket("7b55e0c1", project=None, by="user")
    assert merged.decisions == 1
    text = (engine.paths.memory / "DECISIONS.md").read_text(encoding="utf-8")
    assert "[payments-api] retries use full jitter. why: herd. rejected: fixed delay." in text


TESTED = (
    "project.test_cmd: {cmd!r}\n"
    "agents:\n"
    "  test-runner: {{on: true, cli: shell, skill: run-tests}}\n"
    "workflows:\n"
    "  simple: {{steps: [plan, implement, run_tests, review_code],"
    " on_fail: {{review_code: implement, run_tests: implement}}}}\n"
)


def _tested(engine: Engine, cmd: str) -> None:
    write_settings(engine.paths, TESTED.format(cmd=cmd), slugs=("payments-api",))


def _main_moves(engine: Engine, name: str = "other.py") -> None:
    (engine.repo / name).write_text("from another ticket\n")
    gitops.commit_all(engine.repo, "another ticket merged", {})


def test_merge_reruns_checks_when_base_moved(
    engine: Engine, run_git: Callable[..., str], journal_events: Events
) -> None:
    _tested(engine, "test -f retry.py && test -f other.py")
    ready_to_merge(engine, run_git)
    _main_moves(engine)
    assert merging.merge_ticket("7b55e0c1", project=None, by="user").commits == 1
    checked = [e for e in journal_events() if e["type"] == "checks.end"]
    assert [(e["step"], e["verdict"]) for e in checked] == [("merge", "pass")]


def test_merge_skips_checks_on_the_commit_they_passed_on(
    engine: Engine, run_git: Callable[..., str], journal_events: Events
) -> None:
    _tested(engine, "false")  # would fail if it ran
    ready_to_merge(engine, run_git)
    tested = Checked(commit=gitops.head(engine.worktree), step="implement", summary="ok")
    runtime.save_ticket_state(engine.paths, "7b55e0c1", TicketState(checked=tested))
    merging.merge_ticket("7b55e0c1", project=None, by="user")
    assert not [e for e in journal_events() if e["type"] == "checks.end"]


def test_merge_check_failure_sends_back_and_keeps_main(
    engine: Engine, run_git: Callable[..., str]
) -> None:
    _tested(engine, "test ! -f boom.txt")
    ready_to_merge(engine, run_git)
    _main_moves(engine, "boom.txt")
    with pytest.raises(
        UserError,
        match=r"checks failed after rebase onto main; 7b55e0c1 sent back to implement \(loop 2\)",
    ):
        merging.merge_ticket("7b55e0c1", project=None, by="user")
    doc = engine.ticket()
    assert (doc.meta.status, doc.meta.step, doc.meta.loop) == ("in_queue/ready", "implement", 2)
    assert "test ! -f boom.txt" in doc.sections["Findings"]
    assert doc.sections["Check output"].startswith("`test ! -f boom.txt` exit 1")
    assert not (engine.repo / "retry.py").exists()
    sent = engine.state().sent_back
    assert sent is not None and sent.step == "merge"


def test_merges_of_one_project_serialize(engine: Engine, run_git: Callable[..., str]) -> None:
    ready_to_merge(engine, run_git)
    done: list[Merged] = []
    with locked(engine.paths.locks / "merge-payments-api.lock"):
        worker = threading.Thread(
            target=lambda: done.append(merging.merge_ticket("7b55e0c1", project=None, by="u"))
        )
        worker.start()
        time.sleep(1.0)
        assert done == [] and engine.ticket().meta.status == "in_process/awaiting_merge"
    worker.join(10)
    assert done and engine.ticket().meta.status == "done/merged"


def test_auto_merge_on_a_dirty_tree_journals_why_it_waits(
    engine: Engine, run_git: Callable[..., str], journal_events: Events
) -> None:
    ready_to_merge(engine, run_git)
    (engine.repo / "README.md").write_text("half-edited by the user\n")
    status = merging.merge_if_clean(engine.paths, engine.slug, "7b55e0c1", by="kengash")
    assert status == "in_process/awaiting_merge"
    held = [e for e in journal_events() if e["type"] == "ticket.awaiting_merge"]
    assert [e["reason"] for e in held] == ["main working tree has changes; merge waits for you"]


def test_a_merge_retry_after_unfinished_checks_reruns_them(
    engine: Engine, run_git: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _tested(engine, "test ! -f boom.txt")
    ready_to_merge(engine, run_git)
    tested = Checked(commit=gitops.head(engine.worktree), step="implement", summary="ok")
    runtime.save_ticket_state(engine.paths, "7b55e0c1", TicketState(checked=tested))
    _main_moves(engine, "boom.txt")
    real = checks.outcome
    monkeypatch.setattr(checks, "outcome", lambda result: ("timeout", "checks timed out (60 s)"))
    with pytest.raises(UserError, match="checks could not run after rebase onto main"):
        merging.merge_ticket("7b55e0c1", project=None, by="user")
    assert engine.ticket().meta.status == "in_process/awaiting_merge"
    monkeypatch.setattr(checks, "outcome", real)
    with pytest.raises(UserError, match="checks failed after rebase onto main"):
        merging.merge_ticket("7b55e0c1", project=None, by="user")  # the rebase moves nothing now
    assert not (engine.repo / "retry.py").exists()
