"""CLI formatting of the controls (SP3 spec §10)."""

import os

import pytest
from conftest import Engine
from typer.testing import CliRunner

from super_harness.cli import app
from super_harness.ops import controls
from super_harness.store import StorePaths, documents

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
