"""Provider slots: claims queue, workers take freed slots in arrival order (SP3 decision 17)."""

from pathlib import Path

from conftest import write_settings

from kengash_ai.model import SlotEntry
from kengash_ai.ops import slots
from kengash_ai.scheduler import Held
from kengash_ai.store import StorePaths, runtime


def entry(ticket: str, provider: str = "claude") -> SlotEntry:
    return SlotEntry(provider=provider, project="payments-api", ticket=ticket, step="plan", pid=1)


def test_waiters_take_freed_slots_in_arrival_order(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    write_settings(store_paths, "sessions.per_provider: {claude: 1, codex: 1}\n")
    slots.queue_slot(store_paths, entry("aaaaaaaa"))
    slots.queue_slot(store_paths, entry("bbbbbbbb"))
    assert not slots.acquire(store_paths, entry("bbbbbbbb"))  # aaaaaaaa came first
    assert slots.acquire(store_paths, entry("cccccccc", "codex"))  # another provider is free
    assert slots.acquire(store_paths, entry("aaaaaaaa"))
    assert slots.acquire(store_paths, entry("aaaaaaaa"))  # holding already
    assert not slots.acquire(store_paths, entry("bbbbbbbb"))
    slots.release(store_paths, "aaaaaaaa")
    assert slots.acquire(store_paths, entry("bbbbbbbb"))
    table = runtime.load_slots(store_paths)
    assert [e.ticket for e in table.held] == ["cccccccc", "bbbbbbbb"] and table.waiting == []


def test_occupied_counts_held_and_queued(registered_repo: Path, store_paths: StorePaths) -> None:
    slots.queue_slot(store_paths, entry("aaaaaaaa"))
    slots.acquire(store_paths, entry("bbbbbbbb"))
    assert len(slots.occupied(store_paths)) == 2
    assert slots.occupied(store_paths, exclude="aaaaaaaa") == [Held("payments-api", "claude")]
