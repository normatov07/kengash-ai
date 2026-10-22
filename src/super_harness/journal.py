"""Append-only JSONL journal, one file per UTC day (system spec §6.1)."""

import json
import os
from collections.abc import Iterator
from datetime import date
from typing import Any

from super_harness.model import Event
from super_harness.store.paths import StorePaths
from super_harness.store.redact import redact


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
    for path in sorted(paths.journal.glob("*.jsonl")):
        if since is not None and path.stem < since.isoformat():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                yield Event.model_validate_json(line)


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: _scrub(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value
