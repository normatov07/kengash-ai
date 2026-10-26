"""registry.yaml: project slug → repo path (system spec §4.1)."""

import re
from collections.abc import Collection
from pathlib import Path

from kengash_ai.model import Registry
from kengash_ai.store.files import atomic_write
from kengash_ai.store.paths import StorePaths
from kengash_ai.store.yamlio import dump_yaml, load_yaml


def load_registry(paths: StorePaths) -> Registry:
    if not paths.registry.exists():
        return Registry()
    data = load_yaml(paths.registry.read_text(encoding="utf-8"), "registry.yaml")
    return Registry.model_validate(data or {})


def save_registry(paths: StorePaths, registry: Registry) -> None:
    atomic_write(paths.registry, dump_yaml(registry.model_dump(mode="json")))


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"


def unique_slug(base: str, taken: Collection[str]) -> str:
    slug, counter = base, 2
    while slug in taken:
        slug, counter = f"{base}-{counter}", counter + 1
    return slug


def slug_for_path(registry: Registry, path: Path) -> str | None:
    for slug, entry in registry.projects.items():
        if entry.path == path:
            return slug
    return None
