"""Resolved settings: package defaults, then ~/.harness/defaults, then the project file."""

import difflib
from collections.abc import Mapping
from functools import cache
from typing import Any

from pydantic import ValidationError
from pydantic_core import ErrorDetails

from super_harness.model import Settings, UserError
from super_harness.store.paths import StorePaths
from super_harness.store.seed import package_default
from super_harness.store.yamlio import load_yaml

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


def layers(paths: StorePaths, slug: str | None) -> list[dict[str, Any]]:
    """Package defaults, the user's defaults and the project file, in override order."""
    found = [_parse(package_default("SETTINGS.md"), "package SETTINGS.md")]
    files = [(paths.defaults / "SETTINGS.md", "defaults/SETTINGS.md")]
    if slug is not None:
        files.append((paths.project(slug).settings, f"projects/{slug}/SETTINGS.md"))
    for path, source in files:
        if path.is_file():
            found.append(_parse(path.read_text(encoding="utf-8"), source))
    return found


def load(paths: StorePaths, slug: str | None = None) -> Settings:
    """Validated settings for `slug`, or the user's defaults when `slug` is None."""
    try:
        return _resolve(paths, slug)
    except ValidationError as exc:
        found = [_describe(error) for error in exc.errors()]
        more = f" (+{len(found) - 1} more; run: harness settings check)" if len(found) > 1 else ""
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


def _resolve(paths: StorePaths, slug: str | None) -> Settings:
    resolved: dict[str, Any] = {}
    for layer in layers(paths, slug):
        resolved = merge(resolved, layer)
    return Settings.model_validate(resolved)


def _parse(text: str, source: str) -> dict[str, Any]:
    data = load_yaml(text, source) or {}
    if not isinstance(data, Mapping):
        raise UserError(f"{source}: expected key: value lines")
    return unflatten(data)


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
