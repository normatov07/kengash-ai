"""CLI formatting of the controls (SP3 spec §10)."""

import os

import pytest
from conftest import Engine
from typer.testing import CliRunner

from super_harness import gitops
from super_harness.cli import app
from super_harness.model import SessionRef, WorkerRecord
from super_harness.ops import controls
from super_harness.store import StorePaths, documents, runtime

runner = CliRunner()


@pytest.fixture(autouse=True)
def no_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(controls, "spawn_worker", lambda paths, slug, ticket_id, steps: os.getpid())


def test_run_park_and_pause_print_one_line_each(engine: Engine, store_paths: StorePaths) -> None:
    doc = engine.ticket()
    doc.meta.status, doc.meta.step = "in_queue/ready", None
    documents.save_ticket(store_paths.project(engine.slug), doc)
    started = runner.invoke(app, ["run", "7b55e0c1"])
    assert (started.exit_code, started.stdout) == (0, "started 7b55e0c1 plan→claude\n")
    again = runner.invoke(app, ["run", "7b55e0c1"])
    assert (again.exit_code, again.stdout) == (1, "skipped 7b55e0c1: already running\n")
    paused = runner.invoke(app, ["pause"])
    assert paused.stdout == "paused: 1 running finish their step\n"
    parked = runner.invoke(app, ["park", "7b55e0c1", "--why", "later"])
    assert parked.stdout == "ticket 7b55e0c1 → in_queue/parked after its step\n"


def test_stop_without_a_worker_is_an_error(engine: Engine) -> None:
    result = runner.invoke(app, ["stop", "7b55e0c1"])
    assert result.exit_code == 1 and "7b55e0c1 has no running worker" in result.stderr


def test_wait_on_an_empty_store_is_idle(store_paths: StorePaths) -> None:
    result = runner.invoke(app, ["wait", "--timeout", "1"])
    assert (result.exit_code, result.stdout) == (0, "idle\n")


def test_doctor_reports_a_dead_worker(engine: Engine) -> None:
    runtime.save_worker(
        engine.paths, WorkerRecord(id="7b55e0c1", project=engine.slug, pid=2**22 + 7)
    )
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "payments-api: worker of 7b55e0c1 died; run: harness doctor --fix" in result.stdout
    fixed = runner.invoke(app, ["doctor", "--fix"])
    assert "worker of 7b55e0c1 died; marked failed" in fixed.stdout


def test_ticket_changes_and_attach_print_lines(engine: Engine) -> None:
    (engine.worktree / "retry.py").write_text("a = 1\nb = 2\n")
    trailers = {
        "Harness-Ticket": str(engine.ticket().meta.uuid),
        "Harness-Step": "implement",
        "Harness-Loop": "1",
        "Harness-Agent": "implementer",
        "Harness-Model": "codex/default",
    }
    gitops.commit_all(engine.worktree, "hrn(7b55e0c1): loop 1 implement: retry", trailers)
    listed = runner.invoke(app, ["ticket", "changes", "7b55e0c1"])
    assert listed.stdout == "retry.py +2 -0  loop 1 implement codex/default\n"
    doc = engine.ticket()
    doc.meta.sessions["implementer"] = SessionRef(provider="codex", id="t-1")
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    attached = runner.invoke(app, ["ticket", "attach", "7b55e0c1", "--role", "implementer"])
    assert attached.stdout.strip().endswith("codex resume t-1")
