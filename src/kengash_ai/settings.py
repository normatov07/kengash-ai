"""Resolved settings: package defaults, then ~/.kengash/defaults, then the project file."""

import copy
import difflib
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from pydantic_core import ErrorDetails

from kengash_ai.model import Settings, UserError
from kengash_ai.store import yamledit
from kengash_ai.store.files import atomic_write
from kengash_ai.store.memo import Memo, digest
from kengash_ai.store.paths import StorePaths
from kengash_ai.store.registry import load_registry
from kengash_ai.store.seed import package_default
from kengash_ai.store.yamlio import load_yaml

ATOMIC = frozenset({"workflows"})


def unflatten(data: Mapping[str, Any]) -> dict[str, Any]:
    """Nest dotted keys, recursively: `loop_max.simple: 3` becomes `{loop_max: {simple: 3}}`."""
    out: dict[str, Any] = {}
    for key, raw in data.items():
        value = unflatten(raw) if isinstance(raw, Mapping) else raw
        *parents, leaf = str(key).split(".")
        node = out
        for part in parents:
            child = node.setdefault(part, {})
            if not isinstance(child, dict):
                raise UserError(f"settings: {key} conflicts with {part}")
            node = child
        current = node.get(leaf)
        if isinstance(current, dict) and isinstance(value, dict):
            node[leaf] = merge(current, value)
        elif leaf in node:
            raise UserError(f"settings: {key} conflicts with an earlier key")
        else:
            node[leaf] = value
    return out


def merge(
    base: Mapping[str, Any], override: Mapping[str, Any], path: tuple[str, ...] = ()
) -> dict[str, Any]:
    """Deep-merge `override` onto `base`; each workflow is replaced whole, never mixed."""
    out = dict(base)
    for key, value in override.items():
        current = out.get(key)
        if (
            isinstance(current, Mapping)
            and isinstance(value, Mapping)
            and not (path and path[-1] in ATOMIC)
        ):
            out[key] = merge(current, value, (*path, key))
        else:
            out[key] = value
    return out


# Parsed layers and resolved settings, once per content (SP7 spec decision 1)
_layers: Memo[dict[str, Any]] = Memo(maxsize=256)
_resolved: Memo[Settings] = Memo(maxsize=64)


def layers(paths: StorePaths, slug: str | None) -> list[dict[str, Any]]:
    """Package defaults, the user's defaults and the project file, in override order."""
    return [_parse(text, source) for text, source in _texts(paths, slug)]


def _texts(paths: StorePaths, slug: str | None) -> list[tuple[str, str]]:
    """Each layer's text and the name errors give it."""
    found = [(package_default("SETTINGS.md"), "package SETTINGS.md")]
    files = [(paths.defaults / "SETTINGS.md", "defaults/SETTINGS.md")]
    if slug is not None:
        files.append((paths.project(slug).settings, f"projects/{slug}/SETTINGS.md"))
    for path, source in files:
        if path.is_file():
            found.append((path.read_text(encoding="utf-8"), source))
    return found


def load(paths: StorePaths, slug: str | None = None) -> Settings:
    """Validated settings for `slug`, or the user's defaults when `slug` is None."""
    try:
        return _resolve(paths, slug)
    except ValidationError as exc:
        found = [_describe(error) for error in exc.errors()]
        more = f" (+{len(found) - 1} more; run: kengash settings check)" if len(found) > 1 else ""
        raise UserError(f"settings: {found[0]}{more}") from exc


def problems(paths: StorePaths, slug: str | None = None) -> list[str]:
    """Every problem with the resolved settings; empty when they are valid."""
    try:
        _resolve(paths, slug)
    except UserError as exc:
        return [str(exc)]
    except ValidationError as exc:
        return [_describe(error) for error in exc.errors()]
    return []


def set_values(paths: StorePaths, slug: str | None, changes: Mapping[str, Any]) -> list[str]:
    """Write `changes` (dotted key → value; None removes the key) into one scope's
    SETTINGS.md, touching only their lines; nothing is written unless the result is valid,
    and a defaults save also unless every registered project that resolved before still
    does. Returns the keys that changed."""
    path, source = _scope_file(paths, slug)
    before = path.read_bytes().decode("utf-8") if path.is_file() else ""  # keeps CRLF
    text, done = before, []
    for key, value in changes.items():
        head, _, rest = key.partition(".")
        if head in ATOMIC and "." in rest:
            raise UserError(f"settings: set {head}.{rest.split('.')[0]} whole, not {key}")
        after = yamledit.set_key(text, key, value, source=source)
        if after != text:
            text = after
            done.append(key)
    if not done:
        return []
    found = layers(paths, slug)
    if path.is_file():
        found[-1] = _parse(text, source)
    else:
        found.append(_parse(text, source))
    problem = _first_problem(found)
    if problem:
        raise UserError(f"settings: {problem}")
    if slug is None:
        _check_projects(paths, found)
    atomic_write(path, text)
    return done


def _check_projects(paths: StorePaths, defaults: list[dict[str, Any]]) -> None:
    """Refuse new defaults (package and user layers) under which a registered project that
    resolves today would stop resolving."""
    if not paths.registry.exists():
        return
    for slug in sorted(load_registry(paths).projects):
        own = paths.project(slug).settings
        if not own.is_file() or problems(paths, slug):
            continue  # nothing of its own, or already broken: the defaults check covers it
        layer = _parse(own.read_text(encoding="utf-8"), f"projects/{slug}/SETTINGS.md")
        problem = _first_problem([*defaults, layer])
        if problem:
            raise UserError(f"settings: project {slug} would no longer validate: {problem}")


def _first_problem(found: list[dict[str, Any]]) -> str | None:
    """The first schema problem of the merged layers, or None when they validate."""
    resolved: dict[str, Any] = {}
    for layer in found:
        resolved = merge(resolved, layer)
    try:
        Settings.model_validate(resolved)
    except ValidationError as exc:
        return _describe(exc.errors()[0])
    return None


def scope_keys(paths: StorePaths, slug: str | None) -> list[str]:
    """The dotted leaf keys one scope's SETTINGS.md sets, in file order; a workflow counts
    as one leaf."""
    path, source = _scope_file(paths, slug)
    if not path.is_file():
        return []
    return _leaves(_parse(path.read_text(encoding="utf-8"), source))


def overrides(paths: StorePaths, slug: str | None) -> list[str]:
    """The keys one scope's file sets to a value other than what it would inherit: the
    package defaults for the user's defaults, the user's defaults for a project."""
    path, _ = _scope_file(paths, slug)
    found = layers(paths, slug)
    if not path.is_file():
        return []
    inherited: dict[str, Any] = {}
    for layer in found[:-1]:
        inherited = merge(inherited, layer)
    parent = Settings.model_validate(inherited).model_dump(mode="json")
    own = load(paths, slug).model_dump(mode="json")
    return [key for key in scope_keys(paths, slug) if _at(own, key) != _at(parent, key)]


def get(resolved: Settings, key: str) -> Any:
    """The value at a dotted key, e.g. `loop_max.critical` or `agents.planner`."""
    data = resolved.model_dump(mode="json")
    node: Any = data
    for part in key.split("."):
        if not isinstance(node, Mapping) or part not in node:
            hint = difflib.get_close_matches(key, _flatten(data), n=1)
            raise UserError(
                f"unknown setting {key}" + (f"; did you mean {hint[0]}?" if hint else "")
            )
        node = node[part]
    return node


def _at(data: Mapping[str, Any], key: str) -> Any:
    node: Any = data
    for part in key.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return node


def _scope_file(paths: StorePaths, slug: str | None) -> tuple[Path, str]:
    if slug is None:
        return paths.defaults / "SETTINGS.md", "defaults/SETTINGS.md"
    return paths.project(slug).settings, f"projects/{slug}/SETTINGS.md"


def _leaves(data: Mapping[str, Any], prefix: str = "") -> list[str]:
    keys: list[str] = []
    for key, value in data.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, Mapping) and prefix.rstrip(".") not in ATOMIC:
            keys += _leaves(value, f"{dotted}.")
        else:
            keys.append(dotted)
    return keys


def _resolve(paths: StorePaths, slug: str | None) -> Settings:
    texts = _texts(paths, slug)

    def make() -> Settings:
        resolved: dict[str, Any] = {}
        for text, source in texts:
            resolved = merge(resolved, _parse(text, source))
        return Settings.model_validate(resolved)

    key = tuple(digest(text.encode()) for text, _ in texts)
    return _resolved.get_or_make(key, make).model_copy(deep=True)


def _parse(text: str, source: str) -> dict[str, Any]:
    """One layer as nested keys; errors name `source` and are never cached."""

    def make() -> dict[str, Any]:
        data = load_yaml(text, source) or {}
        if not isinstance(data, Mapping):
            raise UserError(f"{source}: expected key: value lines")
        return unflatten(data)

    return copy.deepcopy(_layers.get_or_make(digest(text.encode()), make))


def _describe(error: ErrorDetails) -> str:
    key = ".".join(str(part) for part in error["loc"])
    if error["type"] == "extra_forbidden":
        hint = difflib.get_close_matches(key, _known_keys(), n=1)
        return f"unknown key {key}" + (f"; did you mean {hint[0]}?" if hint else "")
    message = error["msg"].removeprefix("Value error, ")
    return f"{key}: {message}" if key else message


@cache
def _known_keys() -> list[str]:
    defaults = _parse(package_default("SETTINGS.md"), "package SETTINGS.md")
    return _flatten(Settings.model_validate(defaults).model_dump(mode="json"))


def _flatten(data: Mapping[str, Any], prefix: str = "") -> list[str]:
    keys: list[str] = []
    for key, value in data.items():
        dotted = f"{prefix}{key}"
        keys.append(dotted)
        if isinstance(value, Mapping):
            keys += _flatten(value, f"{dotted}.")
    return keys
