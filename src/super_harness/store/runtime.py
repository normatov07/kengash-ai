"""Engine bookkeeping under runtime/: slots, last claims and pause flags (SP3 spec §4)."""

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ValidationError

from super_harness.model import Claims, HarnessError, SlotTable
from super_harness.store.files import atomic_write
from super_harness.store.paths import StorePaths

PAUSE = "pause"


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
