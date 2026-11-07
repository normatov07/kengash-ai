from datetime import UTC, datetime

import pytest

from kengash_ai.model import (
    Checked,
    Claims,
    JournalCursor,
    KengashError,
    LoopBusy,
    LoopLease,
    SentBack,
    SlotEntry,
    SlotTable,
    TicketState,
    Usage,
    WorkerRecord,
)
from kengash_ai.store import StorePaths, runtime

NOW = datetime(2026, 10, 22, 9, 41, tzinfo=UTC)


def test_slots_and_claims_start_empty_and_round_trip(store_paths: StorePaths) -> None:
    assert runtime.load_slots(store_paths) == SlotTable()
    assert runtime.load_claims(store_paths) == Claims()
    held = SlotEntry(
        provider="claude", project="app", ticket="7b55e0c1", step="plan", pid=42, since=NOW
    )
    runtime.save_slots(store_paths, SlotTable(held=[held]))
    runtime.save_claims(store_paths, Claims(last={"app": NOW}))
    assert runtime.load_slots(store_paths).held == [held]
    assert runtime.load_claims(store_paths).last == {"app": NOW}


def test_pause_flags_cover_one_project_or_everything(store_paths: StorePaths) -> None:
    assert not runtime.pause_state(store_paths).covers("app")
    runtime.set_pause(store_paths, "app", on=True)
    assert runtime.pause_state(store_paths) == runtime.Pause(projects=frozenset({"app"}))
    runtime.set_pause(store_paths, None, on=True)
    assert runtime.pause_state(store_paths).covers("web")
    runtime.set_pause(store_paths, None, on=False)
    runtime.set_pause(store_paths, "app", on=False)
    assert runtime.pause_state(store_paths) == runtime.Pause()


def test_a_damaged_runtime_file_names_itself(store_paths: StorePaths) -> None:
    store_paths.slots.parent.mkdir(parents=True)
    store_paths.slots.write_text("{", encoding="utf-8")
    with pytest.raises(KengashError, match=r"slots\.json: damaged runtime file"):
        runtime.load_slots(store_paths)


def test_worker_records_beat_and_drop(store_paths: StorePaths) -> None:
    runtime.save_worker(store_paths, WorkerRecord(id="7b55e0c1", project="payments-api", pid=4242))
    before = runtime.load_worker(store_paths, "7b55e0c1")
    assert before is not None and before.step is None
    runtime.set_worker_step(store_paths, "7b55e0c1", "implement")
    runtime.beat(store_paths, "7b55e0c1")
    after = runtime.load_worker(store_paths, "7b55e0c1")
    assert after is not None and after.step == "implement" and after.heartbeat >= before.heartbeat
    assert [w.id for w in runtime.load_workers(store_paths)] == ["7b55e0c1"]
    runtime.drop_worker(store_paths, "7b55e0c1")
    runtime.beat(store_paths, "7b55e0c1")
    assert runtime.load_worker(store_paths, "7b55e0c1") is None


def test_ticket_state_park_flags_and_cursors(store_paths: StorePaths) -> None:
    assert runtime.load_ticket_state(store_paths, "7b55e0c1") == TicketState()
    state = TicketState(plan_rounds=1, totals={"doc-writer": Usage(input=5)})
    runtime.save_ticket_state(store_paths, "7b55e0c1", state)
    assert runtime.load_ticket_state(store_paths, "7b55e0c1") == state
    runtime.set_park(store_paths, "7b55e0c1", on=True)
    assert runtime.park_requested(store_paths, "7b55e0c1")
    runtime.set_park(store_paths, "7b55e0c1", on=False)
    assert not runtime.park_requested(store_paths, "7b55e0c1")
    assert runtime.load_cursor(store_paths, "all") is None
    runtime.save_cursor(store_paths, "all", JournalCursor(day="2026-10-23", line=4))
    assert runtime.load_cursor(store_paths, "all") == JournalCursor(day="2026-10-23", line=4)
    assert store_paths.worktree("payments-api", "7b55e0c1") == (
        store_paths.home / "worktrees" / "payments-api" / "kg-7b55e0c1"
    )


def test_lease_round_trip(store_paths: StorePaths) -> None:
    assert runtime.load_leases(store_paths) == []
    assert runtime.load_lease(store_paths, 42) is None
    first = LoopLease(
        pid=42, agent="claude", command="claude", project="app", started=NOW, seen=NOW
    )
    second = LoopLease(pid=7, agent="codex", command="codex", started=NOW, seen=NOW)
    runtime.save_lease(store_paths, first)
    runtime.save_lease(store_paths, second)
    assert runtime.load_lease(store_paths, 42) == first
    assert [lease.pid for lease in runtime.load_leases(store_paths)] == [7, 42]
    assert (store_paths.runtime / "loops" / "42.json").is_file()
    runtime.drop_lease(store_paths, 42)
    runtime.drop_lease(store_paths, 42)  # already gone: nothing happens
    assert runtime.load_leases(store_paths) == [second]


def test_loop_busy_exits_6() -> None:
    assert LoopBusy("loop running: x").exit_code == 6


def test_ticket_state_loads_old_files_and_round_trips_the_new_fields(
    store_paths: StorePaths,
) -> None:
    path = store_paths.runtime / "tickets" / "7b55e0c1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"plan_rounds": 1, "approval": "loop_cap"}', encoding="utf-8")
    old = runtime.load_ticket_state(store_paths, "7b55e0c1")
    assert (old.sent_back, old.checked, old.plan_rounds) == (None, None, 1)
    state = TicketState(
        approval="blocked",
        sent_back=SentBack(step="run_tests", summary="lint failed (exit 1)"),
        checked=Checked(commit="abc1234", step="implement", summary="tests passed"),
    )
    runtime.save_ticket_state(store_paths, "7b55e0c1", state)
    assert runtime.load_ticket_state(store_paths, "7b55e0c1") == state


def test_ticket_state_starts_waiting_on_nobody() -> None:
    assert TicketState().waiting_on == ""
