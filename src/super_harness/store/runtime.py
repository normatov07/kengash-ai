"""Engine bookkeeping under runtime/ (SP3 spec §4): slots, claims, flags, workers, ticket
state, conductor pings and wait cursors, repo trust."""

import threading
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ValidationError

from super_harness.model import (
    Claims,
    ConductorPing,
    HarnessError,
    JournalCursor,
    SlotTable,
    TicketState,
    Trust,
    WorkerRecord,
    utc_now,
)
from super_harness.store.files import atomic_write
from super_harness.store.paths import StorePaths

PAUSE = "pause"
PARK = "park"
_WORKER_LOCK = threading.Lock()  # the heartbeat thread and the step loop share a record


@dataclass(frozen=True)
class Pause:
    """Pause flags: `everything`, or single projects."""

    everything: bool = False
    projects: frozenset[str] = frozenset()

    def covers(self, slug: str) -> bool:
        return self.everything or slug in self.projects


def load_slots(paths: StorePaths) -> SlotTable:
    return _load(paths.slots, SlotTable)


def save_slots(paths: StorePaths, table: SlotTable) -> None:
    _save(paths.slots, table)


def load_claims(paths: StorePaths) -> Claims:
    return _load(paths.claims, Claims)


def save_claims(paths: StorePaths, claims: Claims) -> None:
    _save(paths.claims, claims)


def load_trust(paths: StorePaths) -> Trust:
    return _load(paths.trust, Trust)


def save_trust(paths: StorePaths, trust: Trust) -> None:
    _save(paths.trust, trust)


def load_worker(paths: StorePaths, worker_id: str) -> WorkerRecord | None:
    path = paths.workers / f"{worker_id}.json"
    return _load(path, WorkerRecord) if path.exists() else None


def load_workers(paths: StorePaths) -> list[WorkerRecord]:
    if not paths.workers.is_dir():
        return []
    return [_load(path, WorkerRecord) for path in sorted(paths.workers.glob("*.json"))]


def save_worker(paths: StorePaths, record: WorkerRecord) -> None:
    with _WORKER_LOCK:
        _save(paths.workers / f"{record.id}.json", record)


def drop_worker(paths: StorePaths, worker_id: str) -> None:
    with _WORKER_LOCK:
        (paths.workers / f"{worker_id}.json").unlink(missing_ok=True)


def beat(paths: StorePaths, worker_id: str) -> None:
    """Refresh a worker's heartbeat; nothing happens when it has no record."""
    _update_worker(paths, worker_id, heartbeat=utc_now())


def set_worker_step(paths: StorePaths, worker_id: str, step: str | None) -> None:
    _update_worker(paths, worker_id, step=step)


def load_ticket_state(paths: StorePaths, ticket_id: str) -> TicketState:
    return _load(paths.ticket_states / f"{ticket_id}.json", TicketState)


def save_ticket_state(paths: StorePaths, ticket_id: str, state: TicketState) -> None:
    _save(paths.ticket_states / f"{ticket_id}.json", state)


def drop_ticket_state(paths: StorePaths, ticket_id: str) -> None:
    (paths.ticket_states / f"{ticket_id}.json").unlink(missing_ok=True)


def set_park(paths: StorePaths, ticket_id: str, *, on: bool) -> None:
    """Ask a running worker to park its ticket before the next step, or take that back."""
    flag = paths.flags / f"{PARK}-{ticket_id}"
    if on:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.touch()
    else:
        flag.unlink(missing_ok=True)


def park_requested(paths: StorePaths, ticket_id: str) -> bool:
    return (paths.flags / f"{PARK}-{ticket_id}").exists()


def save_ping(paths: StorePaths, ping: ConductorPing) -> None:
    _save(paths.conductors / f"{ping.pid}.json", ping)


def load_cursor(paths: StorePaths, scope: str) -> JournalCursor | None:
    path = paths.conductors / f"cursor-{scope}.json"
    return _load(path, JournalCursor) if path.exists() else None


def save_cursor(paths: StorePaths, scope: str, cursor: JournalCursor) -> None:
    _save(paths.conductors / f"cursor-{scope}.json", cursor)


def pause_state(paths: StorePaths) -> Pause:
    """`flags/pause` pauses everything; `flags/pause-<slug>` pauses one project."""
    if not paths.flags.is_dir():
        return Pause()
    names = {flag.name for flag in paths.flags.iterdir()}
    prefix = f"{PAUSE}-"
    projects = frozenset(name.removeprefix(prefix) for name in names if name.startswith(prefix))
    return Pause(PAUSE in names, projects)


def set_pause(paths: StorePaths, slug: str | None, *, on: bool) -> None:
    """Pause or resume one project, or everything when `slug` is None."""
    flag = paths.flags / (PAUSE if slug is None else f"{PAUSE}-{slug}")
    if on:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.touch()
    else:
        flag.unlink(missing_ok=True)


def _update_worker(paths: StorePaths, worker_id: str, **changes: object) -> None:
    with _WORKER_LOCK:
        path = paths.workers / f"{worker_id}.json"
        if not path.exists():
            return
        record = _load(path, WorkerRecord).model_copy(update=changes)
        _save(path, record)


def _load[M: BaseModel](path: Path, model: type[M]) -> M:
    if not path.exists():
        return model()
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        problem = exc.errors()[0]["msg"]
        raise HarnessError(f"{path}: damaged runtime file ({problem}); delete it to reset") from exc


def _save(path: Path, data: BaseModel) -> None:
    atomic_write(path, data.model_dump_json(indent=2) + "\n")
