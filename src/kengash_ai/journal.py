"""Append-only JSONL journal, one file per UTC day (system spec §6.1)."""

import json
import os
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

from kengash_ai.model import Event, JournalCursor
from kengash_ai.store.paths import StorePaths
from kengash_ai.store.redact import redact


def append(paths: StorePaths, event: Event) -> None:
    """Write one JSON line with every string redacted; O_APPEND keeps concurrent lines whole."""
    data = _scrub(event.model_dump(mode="json", exclude_none=True))
    line = json.dumps(data, ensure_ascii=False) + "\n"
    paths.journal.mkdir(parents=True, exist_ok=True)
    path = paths.journal / f"{event.ts.date().isoformat()}.jsonl"
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def read(paths: StorePaths, since: date | None = None) -> Iterator[Event]:
    """Events in file order, starting at day `since` (inclusive)."""
    for path in days(paths):
        if since is None or path.stem >= since.isoformat():
            yield from read_day(path)


def days(paths: StorePaths) -> list[Path]:
    """The day files, oldest first."""
    return sorted(paths.journal.glob("*.jsonl"))


def read_day(path: Path) -> list[Event]:
    """The events of one day file, in order."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return [Event.model_validate_json(line) for line in lines if line.strip()]


def read_after(paths: StorePaths, cursor: JournalCursor) -> tuple[list[Event], JournalCursor]:
    """Events written after `cursor`, in order, and the cursor at the journal's end."""
    events: list[Event] = []
    for path in sorted(paths.journal.glob("*.jsonl")):
        if path.stem < cursor.day:
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        skip = cursor.line if path.stem == cursor.day else 0
        events += [Event.model_validate_json(line) for line in lines[skip:] if line.strip()]
        cursor = JournalCursor(day=path.stem, line=len(lines))
    return events, cursor


def end(paths: StorePaths) -> JournalCursor:
    """The position after the last event written so far."""
    days = sorted(paths.journal.glob("*.jsonl"))
    if not days:
        return JournalCursor()
    last = days[-1]
    return JournalCursor(day=last.stem, line=len(last.read_text(encoding="utf-8").splitlines()))


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: _scrub(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value
