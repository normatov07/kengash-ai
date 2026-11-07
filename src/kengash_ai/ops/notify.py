"""A desktop notification when a ticket needs the user (SP13 spec §3.5): sent from
`records.record`, fire and forget; nothing here raises or waits."""

import contextlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence

from kengash_ai import settings
from kengash_ai.model import Event, KengashError, UserError
from kengash_ai.ops import terminals
from kengash_ai.store.paths import StorePaths

BODY_MAX = 200
# event → what happened, and the command that acts on it ({id}: the ticket)
GATES = {
    "ticket.needs_approval": ("needs approval", "kengash approve {id}"),
    "ticket.stalled": ("is stalled", "kengash approve {id}"),
    "ticket.failed": ("failed", "kengash run {id}"),
    "ticket.awaiting_merge": ("is ready to merge", "kengash merge {id}"),
}

which: Callable[[str], str | None] = shutil.which
popen = subprocess.Popen  # the seam tests replace


def argv(
    event: Event, *, platform: str, which: Callable[[str], str | None] = shutil.which
) -> list[str] | None:
    """The command that shows `event` as a notification; None when it needs none or the
    platform has no notifier."""
    body = _body(event)
    if body is None:
        return None
    title = f"kengash · {event.project}" if event.project else "kengash"
    if platform == "darwin":
        if not which("osascript"):
            return None
        script = f"display notification {_quoted(body)} with title {_quoted(title)}"
        return ["osascript", "-e", script]
    if not which("notify-send"):
        return None
    urgency = "critical" if event.type == "ticket.failed" else "normal"
    return ["notify-send", "-a", "kengash", "-u", urgency, title, body]


def send(paths: StorePaths, events: Sequence[Event]) -> None:
    """Notify each event that needs the user, unless notifications are off."""
    if terminals.disabled(os.environ):
        return
    for event in events:
        line = argv(event, platform=sys.platform, which=which)
        if line is None or not _wanted(paths, event.project):
            continue
        with contextlib.suppress(OSError, ValueError, subprocess.SubprocessError):
            popen(
                line,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )


def _quoted(text: str) -> str:
    """An AppleScript string: it reads JSON's quote and backslash escapes, not \\uXXXX."""
    return json.dumps(text, ensure_ascii=False)


def _body(event: Event) -> str | None:
    extra = event.model_extra or {}
    if event.type == "plan.reviewed":
        return f"plan {event.plan} review round {extra.get('round')}: {extra.get('verdict')}"
    if event.type not in GATES or not event.ticket:
        return None
    what, action = GATES[event.type]
    reason = str(extra.get("reason") or "").strip().splitlines()
    said = f": {reason[0]}" if reason else ""
    body = f"{event.ticket} {what}{said} · {action.format(id=event.ticket)}"
    return body if len(body) <= BODY_MAX else body[: BODY_MAX - 1] + "…"


def _wanted(paths: StorePaths, project: str | None) -> bool:
    try:
        return settings.load(paths, project).watch.notify
    except (KengashError, UserError):
        return True
