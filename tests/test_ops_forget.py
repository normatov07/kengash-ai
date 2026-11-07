"""Forgetting a project (SP14 spec §2.2)."""

import os
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import Engine, Events

from kengash_ai.model import LoopLease, TicketState, UserError, WorkerRecord
from kengash_ai.ops import projects
from kengash_ai.ops.conductors import process_name
from kengash_ai.store import StorePaths, runtime
from kengash_ai.store.registry import load_registry


def test_forget_removes_everything_and_the_store_history_keeps_it(
    engine: Engine, run_git: Callable[..., str], journal_events: Events
) -> None:
    runtime.save_ticket_state(engine.paths, engine.ticket_id, TicketState())
    preview = projects.forget_preview("payments-api")
    assert (preview.plans, preview.tickets, preview.worktrees) == (1, 1, 1)
    gone = projects.forget_project("payments-api", by="user")
    assert (gone.slug, gone.plans, gone.tickets, gone.worktrees, gone.link) == (
        "payments-api",
        1,
        1,
        1,
        True,
    )
    assert "payments-api" not in load_registry(engine.paths).projects
    assert not engine.paths.project("payments-api").root.exists()
    assert not (engine.paths.worktrees / "payments-api").exists()
    assert not (engine.paths.ticket_states / f"{engine.ticket_id}.json").exists()
    assert not (engine.repo / ".kengash").exists() and (engine.repo / "README.md").exists()
    assert "kg/7b55e0c1" not in run_git(engine.repo, "branch", "--list")
    assert "kg-7b55e0c1" not in run_git(engine.repo, "worktree", "list")
    event = journal_events()[-1]
    assert (event["type"], event["project"], event["plans"], event["tickets"]) == (
        "project.forgotten",
        "payments-api",
        1,
        1,
    )
    kept = run_git(engine.paths.home, "log", "--name-only", "--format=", "-n", "1")
    assert "projects/payments-api/plans/a1b2c3d4.md" in kept  # removed in the last commit


def test_forget_a_project_whose_repo_is_gone(engine: Engine) -> None:
    shutil.rmtree(engine.repo)
    gone = projects.forget_project("payments-api", by="user")
    assert gone.worktrees == 1 and not gone.link
    assert not (engine.paths.worktrees / "payments-api").exists()


def test_forget_refuses_while_a_worker_or_a_loop_runs(engine: Engine) -> None:
    worker = WorkerRecord(id=engine.ticket_id, project="payments-api", pid=os.getpid())
    runtime.save_worker(engine.paths, worker)
    with pytest.raises(UserError, match="a worker runs 7b55e0c1 in payments-api; stop it first"):
        projects.forget_project("payments-api", by="user")
    runtime.drop_worker(engine.paths, engine.ticket_id)
    lease = LoopLease(
        pid=os.getpid(),
        agent="claude",
        command=process_name(os.getpid()) or "",
        project="payments-api",
    )
    runtime.save_lease(engine.paths, lease)
    with pytest.raises(UserError, match="a loop runs on payments-api"):
        projects.forget_project("payments-api", by="user")
    assert "payments-api" in load_registry(engine.paths).projects


def test_forget_an_unknown_project(store_paths: StorePaths) -> None:
    with pytest.raises(UserError, match="unknown project: nope"):
        projects.forget_project("nope", by="user")


def test_doctor_names_forget_for_a_missing_repo(store_paths: StorePaths, repo: Path) -> None:
    projects.init_project(repo)
    shutil.rmtree(repo)
    [problem] = projects.doctor().problems
    assert problem.message.endswith(
        "; if it moved: kengash link payments-api <new-path>; if it is gone for good: "
        "kengash forget payments-api"
    )


def test_the_cli_asks_unless_yes(engine: Engine) -> None:
    from typer.testing import CliRunner

    from kengash_ai.cli import app

    runner = CliRunner()
    asked = runner.invoke(app, ["forget", "payments-api"])
    assert asked.exit_code == 5
    assert asked.stderr.startswith("forget payments-api removes 1 plans, 1 tickets, 1 worktrees")
    assert "payments-api" in load_registry(engine.paths).projects
    done = runner.invoke(app, ["forget", "payments-api", "--yes", "--by", "user"])
    assert (done.exit_code, done.stdout) == (
        0,
        "forgot payments-api: 1 plans, 1 tickets, 1 worktrees removed; "
        "the store's git history keeps them\n",
    )


def test_the_preview_counts_worktrees_holding_uncommitted_work(engine: Engine) -> None:
    (engine.worktree / "retry.py").write_text("x = 1\n", encoding="utf-8")
    assert projects.forget_preview("payments-api").dirty == 1
    from typer.testing import CliRunner

    from kengash_ai.cli import app

    asked = CliRunner().invoke(app, ["forget", "payments-api"])
    assert "1 with uncommitted changes, which are lost" in asked.stderr
