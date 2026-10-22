from datetime import UTC, datetime

import pytest

from super_harness.model import Claims, HarnessError, SlotEntry, SlotTable
from super_harness.store import StorePaths, runtime

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
    with pytest.raises(HarnessError, match=r"slots\.json: damaged runtime file"):
        runtime.load_slots(store_paths)
