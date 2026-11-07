"""kengash wait progress, ps and logs (SP12 spec §4.3, §4.4)."""

import json

import pytest
from conftest import Engine
from typer.testing import CliRunner

from kengash_ai.cli import app
from kengash_ai.store import documents

runner = CliRunner()


@pytest.fixture
def busy(busy_ticket: Engine, monkeypatch: pytest.MonkeyPatch) -> Engine:
    monkeypatch.chdir(busy_ticket.repo)
    return busy_ticket


def test_wait_timeout_prints_progress(busy: Engine) -> None:
    runner.invoke(app, ["wait", "--timeout", "0.1"])  # sets the cursor
    result = runner.invoke(app, ["wait", "--timeout", "0.3"])
    assert result.exit_code == 3
    assert result.stdout.startswith(f"{busy.ticket_id} implement→antigravity/flash 12m · active ")
    assert "wait timed out after 0.3 s" in result.stderr


def test_wait_defaults_to_five_minutes() -> None:
    assert "[default: 300" in runner.invoke(app, ["wait", "--help"]).stdout


def test_ps_lines_and_line_mode(busy: Engine) -> None:
    lines = runner.invoke(app, ["ps"]).stdout.splitlines()
    assert len(lines) == 1 and lines[0].startswith(f"{busy.ticket_id} implement→antigravity/flash")
    short = runner.invoke(app, ["ps", "--line"]).stdout
    assert short == (
        f"kg: 1 running · {busy.ticket_id} implement→antigravity 12m "
        "reply: Rebrand core package and UI to Chess Samurai\n"
    )
    data = json.loads(runner.invoke(app, ["ps", "--json"]).stdout)
    assert data[0]["id"] == busy.ticket_id and data[0]["alive"] is True


def test_ps_nothing_running(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(engine.repo)
    doc = engine.ticket()
    doc.meta.status = "in_process/awaiting_merge"
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    assert runner.invoke(app, ["ps"]).stdout == "nothing running\n"
    assert runner.invoke(app, ["ps", "--line"]).stdout == "kg: nothing running\n"


def test_logs_prints_history(busy: Engine) -> None:
    lines = runner.invoke(app, ["logs", busy.ticket_id]).stdout.splitlines()
    texts = [line.split(" ", 1)[1] for line in lines]
    assert texts[0] == "implement → antigravity"
    assert texts[1:] == [
        "read /work/pubspec.yaml",  # the fixture's paths lie outside this worktree
        "edit /work/lib/main.dart",
        "reply: Rebrand core package and UI to Chess Samurai",
    ]
    assert all(len(line.split(" ", 1)[0]) == 8 for line in lines)  # HH:MM:SS


def test_logs_follow_ends(busy: Engine) -> None:
    doc = busy.ticket()
    doc.meta.status, doc.meta.step = "done/merged", None
    documents.save_ticket(busy.paths.project(busy.slug), doc)
    result = runner.invoke(app, ["logs", busy.ticket_id, "-f"])
    assert result.exit_code == 0 and result.stdout.splitlines()[-1].endswith(" done/merged")


def test_logs_watch_registers_its_tab_and_ends_when_done(
    busy: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kengash_ai.ops import viewers

    held: list[bool] = []
    real = viewers.register

    def register(paths: object, key: str) -> None:
        real(paths, key)  # type: ignore[arg-type]
        held.append(viewers.live(busy.paths, key))

    monkeypatch.setattr(viewers, "register", register)
    doc = busy.ticket()
    doc.meta.status, doc.meta.step = "done/merged", None
    documents.save_ticket(busy.paths.project(busy.slug), doc)
    result = runner.invoke(app, ["logs", busy.ticket_id, "--watch"])
    assert result.exit_code == 0 and result.stdout.splitlines()[-1].endswith(" done/merged")
    assert held == [True] and not viewers.live(busy.paths, f"ticket-{busy.ticket_id}")
