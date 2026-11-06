"""What a ticket's workers did, as readable lines: parsed from the CLIs' stream logs and the
journal, shared by `kengash logs` and the UI's Live tab (SP12 spec §4.4, §4.5)."""

import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from kengash_ai import journal
from kengash_ai.adapters import stream
from kengash_ai.model import Event, Folder
from kengash_ai.ops import records
from kengash_ai.ops.workspace import GATES
from kengash_ai.store.paths import StorePaths

type Kind = Literal["step", "read", "edit", "run", "reply", "error", "status"]
TAIL_BYTES = 64 * 1024  # a long step's log is read from its end
TEXT_MAX = 160

# tool names per CLI → kind; anything else counts as `run`
_AGY: dict[str, Kind] = {
    "read_file": "read",
    "view_file": "read",
    "list_dir": "read",
    "grep_search": "read",
    "find_by_name": "read",
    "codebase_search": "read",
    "edit_file": "edit",
    "write_to_file": "edit",
    "replace_file_content": "edit",
    "multi_replace_file_content": "edit",
    "create_file": "edit",
    "delete_file": "edit",
}
_CLAUDE: dict[str, Kind] = {
    "Read": "read",
    "Grep": "read",
    "Glob": "read",
    "LS": "read",
    "Edit": "edit",
    "Write": "edit",
    "MultiEdit": "edit",
    "NotebookEdit": "edit",
    "Bash": "run",
}
_TARGETS = ("file_path", "path", "pattern", "command")
_AGY_TARGETS = ("TargetFile", "Path", "AbsolutePath", "File", "FilePath", "CommandLine", "Query")
_SKIP_TOOLS = {"finish", "StructuredOutput"}


@dataclass(frozen=True)
class Activity:
    ts: datetime | None
    kind: Kind
    text: str


def parse(
    text: str, stamps: list[datetime] | None = None, *, root: Path | None = None
) -> list[Activity]:
    """One Activity per worker action in a claude, agy or codex stream; `stamps` (one per
    line of `text`) time them."""
    found: list[Activity] = []
    for number, line in enumerate(text.split("\n")):  # JSON keeps U+2028 raw
        events = stream.lines(line)
        if not events:
            continue
        ts = stamps[number] if stamps and number < len(stamps) else None
        for kind, said in _actions(events[0], root):
            found.append(Activity(ts, kind, _end(said) if kind == "error" else _short(said)))
    return found


def ticket(
    paths: StorePaths, slug: str, ticket_id: str, *, root: Path | None = None
) -> list[Activity]:
    """The ticket's journal steps and statuses with every worker action of its logs, in
    time order."""
    root = root or paths.worktree(slug, ticket_id)
    doc = records.project_tickets(paths, slug).get(ticket_id)
    since = doc.meta.created.date() if doc is not None else None
    events = _journal(paths, slug, ticket_id, since)
    found = [item for event in events if (item := _from_event(event))]
    for log in _logs(paths, ticket_id):
        text, stamps = _read(log)
        found += parse(text, stamps, root=root)
    order = {id(item): n for n, item in enumerate(found)}
    floor = datetime.min.replace(tzinfo=UTC)
    return sorted(found, key=lambda item: (item.ts or floor, order[id(item)]))


def follow(
    paths: StorePaths,
    slug: str,
    ticket_id: str,
    *,
    poll_s: float = 1.0,
    root: Path | None = None,
    heartbeat: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[Activity | None]:
    """Every activity so far, then each new one as it happens, until the ticket stops
    running; the last line is its status. With `heartbeat`, a poll that finds nothing new
    yields None, so a stream can check that its client is still there."""
    seen: set[tuple[datetime | None, str, str]] = set()
    while True:
        status, running = _state(paths, slug, ticket_id)
        fresh = False
        for item in ticket(paths, slug, ticket_id, root=root):
            key = (item.ts, item.kind, item.text)
            if key not in seen:
                seen.add(key)
                fresh = True
                yield item
        if not running:
            yield Activity(datetime.now(UTC), "status", status)
            return
        if heartbeat and not fresh:
            yield None
        sleep(poll_s)


def history(ticket_id: str, project: str | None) -> list[Activity]:
    """`ticket` for a ticket of the user's store, found by id."""
    paths = StorePaths.default()
    slug, _ = records.locate_ticket(paths, ticket_id, project)
    return ticket(paths, slug, ticket_id)


def watch(
    ticket_id: str, project: str | None, *, poll_s: float = 1.0, heartbeat: bool = False
) -> Iterator[Activity | None]:
    """`follow` for a ticket of the user's store, found by id."""
    paths = StorePaths.default()
    slug, _ = records.locate_ticket(paths, ticket_id, project)
    return follow(paths, slug, ticket_id, poll_s=poll_s, heartbeat=heartbeat)


def running_status(status: str) -> bool:
    """A status at which a worker is busy with the ticket."""
    folder, _, sub = status.partition("/")
    return folder == Folder.in_process.value and sub not in (*GATES, "paused", "failed")


def _state(paths: StorePaths, slug: str, ticket_id: str) -> tuple[str, bool]:
    doc = records.project_tickets(paths, slug).get(ticket_id)
    status = doc.meta.status if doc else "gone"
    return status, running_status(status)


def _journal(paths: StorePaths, slug: str, ticket_id: str, since: date | None) -> list[Event]:
    """The ticket's events, read from the day it was made (not every day, every poll)."""
    return [e for e in journal.read(paths, since) if e.project == slug and e.ticket == ticket_id]


def _from_event(event: Event) -> Activity | None:
    extra = event.model_extra or {}
    if event.type == "step.start":
        return Activity(event.ts, "step", f"{extra.get('step')} → {extra.get('provider')}")
    if event.type == "step.end":
        tokens = extra.get("tokens") or {}
        used = int(tokens.get("in", 0)) + int(tokens.get("out", 0))
        files = extra.get("files")
        parts = [f"{extra.get('step')} {extra.get('verdict')}"]
        parts += [f"{files} files"] if files else []
        parts += [f"{round(used / 1000)}k tokens"] if used else []
        return Activity(event.ts, "step", " · ".join(parts))
    if event.type in ("ticket.failed", "ticket.stalled", "ticket.needs_approval"):
        why = str(extra.get("reason") or "").splitlines()
        state = event.type.removeprefix("ticket.")
        return Activity(event.ts, "status", _short(f"{state}: {why[0]}" if why else state))
    if event.type in ("ticket.awaiting_merge", "ticket.merged"):
        return Activity(event.ts, "status", event.type.removeprefix("ticket."))
    return None


def _logs(paths: StorePaths, ticket_id: str) -> list[Path]:
    def number(path: Path) -> int:
        tail = path.stem.rsplit("-", 1)[-1]
        return int(tail) if tail.isdigit() else 0

    return sorted(paths.logs.glob(f"{ticket_id}-*.out"), key=number)


def _read(log: Path) -> tuple[str, list[datetime] | None]:
    """The log's last TAIL_BYTES, and the stamps of those lines (else the file's mtime)."""
    data = log.read_bytes()
    skipped = data[: max(len(data) - TAIL_BYTES, 0)].count(b"\n")
    text = data[-TAIL_BYTES:].decode("utf-8", errors="replace")
    if len(data) > TAIL_BYTES:
        text = text.split("\n", 1)[-1]  # drop the cut line
        skipped += 1
    stamps_file = log.with_suffix(".ts")
    if stamps_file.is_file():
        lines = stamps_file.read_text(encoding="utf-8").split()[skipped:]
        return text, [datetime.fromisoformat(stamp) for stamp in lines]
    mtime = datetime.fromtimestamp(log.stat().st_mtime, UTC)
    return text, [mtime] * len(text.split("\n"))


def _actions(event: dict[str, Any], root: Path | None) -> list[tuple[Kind, str]]:
    if "event" in event:  # agy
        return _agy(event, root)
    kind = str(event.get("type") or "")
    if kind.startswith(("item.", "thread.", "turn.")) or kind == "error":
        return _codex(event, root)
    return _claude(event, root)


def _agy(event: dict[str, Any], root: Path | None) -> list[tuple[Kind, str]]:
    if event.get("event") == "result":
        result = event.get("result") or {}
        found = _reply(result.get("structured_output"), result.get("response"))
        if result.get("status") not in (None, "SUCCESS") and result.get("error"):
            found.append(("error", f"error: {_first(str(result['error']))}"))
        return found
    update = event.get("step_update") or {}
    tool = str(update.get("tool_name") or "")
    if update.get("step_type") != "tool" or update.get("state") != "DONE" or tool in _SKIP_TOOLS:
        return []
    info = update.get("tool_info") or {}
    if isinstance(info, str):
        info = _json(info)
    params = info.get("parameters") or {} if isinstance(info, dict) else {}
    target = next((str(params[key]) for key in _AGY_TARGETS if params.get(key)), "")
    kind = _AGY.get(tool, "run")
    return [
        (
            kind,
            f"{kind} {_rel(target, root)}".strip()
            if kind != "run"
            else f"run {tool} {target}".strip(),
        )
    ]


def _claude(event: dict[str, Any], root: Path | None) -> list[tuple[Kind, str]]:
    if event.get("type") == "result":
        if event.get("is_error"):
            return [("error", f"error: {_first(str(event.get('result') or ''))}")]
        return []
    if event.get("type") != "assistant":
        return []
    found: list[tuple[Kind, str]] = []
    for part in (event.get("message") or {}).get("content") or []:
        if not isinstance(part, dict) or part.get("type") != "tool_use":
            continue
        name, params = str(part.get("name")), part.get("input") or {}
        if name == "StructuredOutput":
            found += _reply(params, None)
            continue
        target = next((str(params[key]) for key in _TARGETS if params.get(key)), "")
        kind = _CLAUDE.get(name, "run")
        label = target if kind == "run" and name == "Bash" else _rel(target, root)
        found.append((kind, f"{kind} {label}".strip() if name in _CLAUDE else f"run {name}"))
    return found


def _codex(event: dict[str, Any], root: Path | None) -> list[tuple[Kind, str]]:
    if event.get("type") == "turn.failed":
        message = (event.get("error") or {}).get("message") or "turn failed"
        return [("error", f"error: {_first(str(message))}")]
    if event.get("type") != "item.completed":
        return []
    item = event.get("item") or {}
    kind = item.get("type")
    if kind == "command_execution":
        return [("run", f"run {item.get('command', '')}")]
    if kind == "file_change":
        paths = [_rel(str(change.get("path", "")), root) for change in item.get("changes") or []]
        return [("edit", f"edit {', '.join(paths)}")]
    if kind == "agent_message":
        return _reply(None, item.get("text"))
    return []


def _reply(structured: object, response: object) -> list[tuple[Kind, str]]:
    """The step's reply: the structured output's summary, else the response's first line."""
    data = structured if isinstance(structured, dict) else _json(str(response or ""))
    summary = data.get("summary") if isinstance(data, dict) else None
    text = str(summary) if summary else _first(str(response or ""))
    return [("reply", f"reply: {text}")] if text else []


def _json(text: str) -> dict[str, Any]:
    for candidate in (text.strip(), *reversed(text.strip().splitlines())):
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def _rel(target: str, root: Path | None) -> str:
    if root is not None and target.startswith(f"{root}/"):
        return target[len(str(root)) + 1 :]
    return target


def _first(text: str) -> str:
    lines = text.strip().splitlines()
    return lines[0].strip() if lines else ""


def _short(text: str) -> str:
    return text if len(text) <= TEXT_MAX else text[: TEXT_MAX - 1] + "…"


def _end(text: str) -> str:
    """An error keeps its end, where the cause is: `error: …read: connection reset by peer`."""
    head = "error: "
    if len(text) <= TEXT_MAX:
        return text
    return head + "…" + text[-(TEXT_MAX - len(head) - 1) :]
