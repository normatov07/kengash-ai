"""Stream output of the worker CLIs: one JSON object per line (SP12 spec §4.1)."""

import json
from typing import Any


def lines(text: str) -> list[dict[str, Any]]:
    """The JSON objects in `text`, one per line; other lines are skipped."""
    found: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            found.append(value)
    return found


def result(text: str, *, key: str, value: str) -> dict[str, Any] | None:
    """The last event whose `key` equals `value`; else the whole text as one JSON object
    (the CLIs' `json` format, which older recordings and the fake CLIs use); else None."""
    events = lines(text)
    match = next((event for event in reversed(events) if event.get(key) == value), None)
    if match is not None:
        return match
    try:
        whole = json.loads(text)
    except json.JSONDecodeError:
        return None
    return whole if isinstance(whole, dict) else None


def first(text: str, *, key: str, value: str) -> dict[str, Any] | None:
    """The first event whose `key` equals `value`, or None."""
    return next((event for event in lines(text) if event.get(key) == value), None)
