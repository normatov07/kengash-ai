import json
import stat
from datetime import UTC, date, datetime

from kengash_ai import journal
from kengash_ai.model import Event, JournalCursor
from kengash_ai.store import StorePaths

TS = datetime(2026, 10, 22, 12, 4, 11, tzinfo=UTC)


def test_events_append_as_redacted_json_lines(store_paths: StorePaths) -> None:
    journal.append(
        store_paths, Event(ts=TS, type="memory.write", project="app", why="token=abc123")
    )
    journal.append(store_paths, Event(ts=TS, type="step.end", ticket="4f2a1b7c", loop=2))
    path = store_paths.journal / "2026-10-22.jsonl"
    first, second = path.read_text(encoding="utf-8").splitlines()
    assert json.loads(first) == {
        "ts": "2026-10-22T12:04:11Z",
        "type": "memory.write",
        "project": "app",
        "why": "token=[REDACTED]",
    }
    assert json.loads(second)["loop"] == 2
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_read_returns_events_in_order_with_extras(store_paths: StorePaths) -> None:
    journal.append(store_paths, Event(ts=TS, type="a"))
    journal.append(store_paths, Event(ts=TS, type="b", files=3))
    events = list(journal.read(store_paths))
    assert [event.type for event in events] == ["a", "b"]
    assert events[1].model_extra == {"files": 3}


def test_read_since_skips_older_days(store_paths: StorePaths) -> None:
    journal.append(store_paths, Event(ts=datetime(2026, 10, 21, tzinfo=UTC), type="old"))
    journal.append(store_paths, Event(ts=TS, type="new"))
    assert [event.type for event in journal.read(store_paths, since=date(2026, 10, 22))] == ["new"]


def test_read_after_returns_each_event_once(store_paths: StorePaths) -> None:
    start = journal.end(store_paths)
    assert start == JournalCursor()
    journal.append(store_paths, Event(ts=datetime(2026, 10, 22, 23, 59, tzinfo=UTC), type="a"))
    journal.append(store_paths, Event(ts=datetime(2026, 10, 23, 0, 1, tzinfo=UTC), type="b"))
    events, cursor = journal.read_after(store_paths, start)
    assert [e.type for e in events] == ["a", "b"] and cursor == JournalCursor(
        day="2026-10-23", line=1
    )
    journal.append(store_paths, Event(ts=datetime(2026, 10, 23, 0, 2, tzinfo=UTC), type="c"))
    events, cursor = journal.read_after(store_paths, cursor)
    assert [e.type for e in events] == ["c"] and cursor == journal.end(store_paths)
