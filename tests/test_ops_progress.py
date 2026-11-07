"""Running tickets at a glance (SP12 spec §4.2)."""

import os
from datetime import UTC, datetime, timedelta

import pytest
from conftest import FAKES, Engine

from kengash_ai import journal
from kengash_ai.model import Event, Running, TicketState, WorkerRecord
from kengash_ai.ops import progress
from kengash_ai.store import runtime

NOW = datetime(2026, 11, 6, 6, 17, tzinfo=UTC)
STARTED = NOW - timedelta(minutes=12)


@pytest.fixture
def busy(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Engine:
    """The ticket implementing on agy for 12 minutes, its worker alive, one file changed."""
    monkeypatch.setattr(progress, "utc_now", lambda: NOW)
    progress.forget()
    log = engine.paths.logs / f"{engine.ticket_id}-3.out"
    log.parent.mkdir(parents=True, exist_ok=True)
    text = (FAKES / "fixtures" / "agy" / "stream-ok.jsonl").read_text(encoding="utf-8")
    log.write_text(text, encoding="utf-8")
    stamps = [(NOW - timedelta(seconds=40)).isoformat()] * len(text.splitlines())
    log.with_suffix(".ts").write_text("\n".join(stamps) + "\n", encoding="utf-8")
    os.utime(log, (NOW.timestamp() - 40, NOW.timestamp() - 40))
    running = Running(role="implementer", provider="antigravity", model="flash", log=log)
    runtime.save_ticket_state(engine.paths, engine.ticket_id, TicketState(running=running))
    doc = engine.ticket()
    doc.meta.status, doc.meta.step = "in_process/under_implementation", "implement"
    from kengash_ai.store import documents

    documents.save_ticket(engine.paths.project(engine.slug), doc)
    worker = WorkerRecord(id=engine.ticket_id, project=engine.slug, pid=os.getpid(), heartbeat=NOW)
    runtime.save_worker(engine.paths, worker)
    data = {"ts": STARTED, "type": "step.start", "project": engine.slug, "ticket": engine.ticket_id}
    journal.append(engine.paths, Event.model_validate({**data, "step": "implement"}))
    changed = engine.worktree / "lib" / "main.dart"
    changed.parent.mkdir(parents=True, exist_ok=True)
    changed.write_text("void main() {}\n", encoding="utf-8")
    os.utime(changed, (NOW.timestamp() - 90, NOW.timestamp() - 90))
    return engine


def test_progress_line(busy: Engine) -> None:
    (found,) = progress.running(busy.paths, [busy.slug])
    assert progress.line(found) == (
        f"{busy.ticket_id} implement→antigravity/flash 12m · active 40s ago · "
        "1 files changed · reply: Rebrand core package and UI to Chess Samurai"
    )


def test_progress_marks_quiet(busy: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    later = NOW + timedelta(minutes=11)
    monkeypatch.setattr(progress, "utc_now", lambda: later)
    worker = WorkerRecord(id=busy.ticket_id, project=busy.slug, pid=os.getpid(), heartbeat=later)
    runtime.save_worker(busy.paths, worker)  # alive, but silent for 11 minutes
    (found,) = progress.running(busy.paths, [busy.slug])
    assert found.quiet and progress.line(found).endswith(" · quiet")


def test_progress_marks_a_dead_worker(busy: Engine) -> None:
    runtime.drop_worker(busy.paths, busy.ticket_id)
    (found,) = progress.running(busy.paths, [busy.slug])
    assert not found.alive and progress.line(found).endswith(" · worker gone")


def test_progress_counts_worktree_changes(busy: Engine) -> None:
    (busy.worktree / "new.txt").write_text("x\n", encoding="utf-8")
    progress.forget()
    (found,) = progress.running(busy.paths, [busy.slug])
    assert found.changed == 2


def test_nothing_running(engine: Engine) -> None:
    doc = engine.ticket()
    doc.meta.status = "in_process/awaiting_merge"
    from kengash_ai.store import documents

    documents.save_ticket(engine.paths.project(engine.slug), doc)
    assert progress.running(engine.paths, [engine.slug]) == []


def test_progress_between_calls_names_no_cli(busy: Engine) -> None:
    runtime.save_ticket_state(busy.paths, busy.ticket_id, TicketState())  # no CLI runs now
    (found,) = progress.running(busy.paths, [busy.slug])
    line = progress.line(found)
    assert line.startswith(f"{busy.ticket_id} implement (between calls) 12m · ")
    assert "→" not in line and "/ " not in line
    assert progress.short([found]).startswith(
        f"kg: 1 running · {busy.ticket_id} implement (between calls) 12m"
    )
