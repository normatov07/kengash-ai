"""Settings edits shared by the UI screens (SP5 spec decision 7): one scope's SETTINGS.md,
changed key by key, journaled and committed."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from kengash_ai import settings
from kengash_ai.model import Event
from kengash_ai.ops import records
from kengash_ai.store.locks import locked
from kengash_ai.store.paths import StorePaths


@dataclass
class Saved:
    project: str | None
    keys: list[str] = field(default_factory=list)


def save_settings(changes: Mapping[str, Any], *, project: str | None, by: str) -> Saved:
    """Apply `changes` (dotted key → value, None removes) to the defaults or one project."""
    paths = StorePaths.default()
    if project is not None:
        records.scope(paths, project)  # an unknown project fails here, naming it
    with locked(paths.locks / "settings.lock"):
        keys = settings.set_values(paths, project, changes)
    if keys:
        event = Event(type="settings.changed", project=project, keys=keys, by=by)
        records.record(paths, f"harness: settings {project or 'defaults'}", event)
    return Saved(project, keys)
