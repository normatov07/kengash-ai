"""Merge: rebase onto the base branch, fast-forward, clean up (SP3 spec §9, decision 23)."""

from collections.abc import Callable

import pytest
from conftest import Engine

from kengash_ai import gitops
from kengash_ai.model import Doc, Ticket, UserError
from kengash_ai.ops import changes, merging, records
from kengash_ai.ops.merging import Merged
from kengash_ai.store import documents

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
        merging.merge_if_clean(engine.paths, engine.slug, "7b55e0c1", by="harness")
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
