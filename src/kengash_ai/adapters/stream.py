"""Stream output of the worker CLIs: one JSON object per line (SP12 spec §4.1)."""

import json
from typing import Any


def _event(line: str) -> dict[str, Any] | None:
    if not line.startswith("{"):
        return None
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _split(text: str) -> list[str]:
    # not splitlines(): JSON keeps U+2028 and U+0085 raw
    return [line.strip() for line in text.split("\n") if line.strip()]


def lines(text: str) -> list[dict[str, Any]]:
    """The JSON objects in `text`, one per line; other lines are skipped."""
    return [event for line in _split(text) if (event := _event(line)) is not None]


def said(text: str) -> str:
    """What the CLI itself said in a stream: its lines that are not JSON and each event's
    `error`. The model's text is left out: it may name a quota or a dropped connection
    without either having happened."""
    kept: list[str] = []
    for line in _split(text):
        event = _event(line)
        if event is None:
            kept.append(line)
            continue
        error = event.get("error")
        message = error.get("message") if isinstance(error, dict) else error
        if message:
            kept.append(str(message))
    return "\n".join(kept)


def result(text: str, *, key: str, value: str) -> dict[str, Any] | None:
    """The last event whose `key` equals `value`; else the whole text as one JSON object
    (the CLIs' `json` format, which older recordings and the fake CLIs use); else None."""
    events = lines(text)
    match: dict[str, Any] | None = next(
        (event for event in reversed(events) if event.get(key) == value), None
    )
    if match is not None:
        return match
    try:
        whole: object = json.loads(text)
    except json.JSONDecodeError:
        return None
    return whole if isinstance(whole, dict) else None


def first(text: str, *, key: str, value: str) -> dict[str, Any] | None:
    """The first event whose `key` equals `value`, or None."""
    return next((event for event in lines(text) if event.get(key) == value), None)
