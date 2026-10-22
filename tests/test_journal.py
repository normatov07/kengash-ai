import json
import stat
from datetime import UTC, date, datetime

from super_harness import journal
from super_harness.model import Event
from super_harness.store import StorePaths

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
