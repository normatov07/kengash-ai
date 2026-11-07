"""Edit one dotted key of a YAML file in place (SP5 spec decision 7). Round-trip YAML only
locates the lines; every line the edit does not touch stays byte-identical, and every line
it writes ends as the text's first line does (CRLF stays CRLF)."""

import json
import re
from collections.abc import Mapping
from functools import cache
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError

from kengash_ai.model import UserError

_PLAIN = re.compile(r"[A-Za-z_~/.][\w./@~+-]*")

Path_ = list[tuple[CommentedMap, str]]  # (mapping, key) from the root down


def set_key(text: str, key: str, value: Any, *, source: str = "YAML") -> str:
    """`text` with dotted `key` set to `value`, or removed when `value` is None.

    At each mapping the longest dotted prefix present wins (`loop_max.simple` before
    `loop_max`). A scalar replacing a one-line scalar is swapped in place; anything else
    rewrites the nearest entry of a block mapping on one line, in flow style.
    """
    cr = "\r" if "\n" in text and text.partition("\n")[0].endswith("\r") else ""
    if not text or text.endswith("\n"):
        return _set(text, key, value, source, cr)
    # an unterminated last line is ended while editing, so every line written gets the ending
    return _set(f"{text}{cr}\n", key, value, source, cr).removesuffix(f"{cr}\n")


def rename_key(text: str, old: str, new: str, *, source: str = "YAML") -> str:
    """`text` with top-level key `old` renamed `new` on its own line, its value and comment
    kept; unchanged when `old` is missing, quoted, or `new` is already there."""
    root = _load(text, source)
    if not isinstance(root, CommentedMap) or old not in root or new in root:
        return text
    line, column = root.lc.key(old)
    lines = text.split("\n")
    row = lines[line]
    if row[column : column + len(old)] != old:
        return text
    lines[line] = row[:column] + new + row[column + len(old) :]
    return "\n".join(lines)


def _load(text: str, source: str) -> object:
    try:
        return YAML(typ="rt").load(text)
    except YAMLError as exc:
        raise UserError(f"{source}: invalid YAML: {getattr(exc, 'problem', exc)}") from exc


def _set(text: str, key: str, value: Any, source: str, cr: str) -> str:
    """`set_key` on a text whose last line is ended; `cr` ends each line written."""
    root = _load(text, source)
    if root is None:
        root = CommentedMap()
    if not isinstance(root, CommentedMap):
        raise UserError(f"{source}: expected key: value lines")
    lines = text.split("\n")
    found, rest = _walk(root, key.split("."), key)
    if rest:  # the key is missing below found's last mapping
        if value is None:
            return text
        holder = found[-1][0][found[-1][1]] if found else root
        if found and holder.fa.flow_style():
            return _rewrite(lines, found, rest, value, cr)
        return _insert(lines, holder, ".".join(rest), value, cr, top=not found)
    mapping, leaf = found[-1]
    current = mapping[leaf]
    if value is not None and _plain(current) == value:
        return text
    if value is None:
        return _remove(lines, found, cr)
    if _scalar(current) and _scalar(value):
        swapped = _swap(lines, mapping, leaf)
        if swapped is not None:
            line, start, end = swapped
            lines[line] = lines[line][:start] + flow(value) + lines[line][end:]
            return "\n".join(lines)
    return _rewrite(lines, found, [], value, cr)


def flow(value: Any) -> str:
    """`value` as one line of flow-style YAML."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        return value if _plain_ok(value) else json.dumps(value, ensure_ascii=False)
    if isinstance(value, Mapping):
        return "{" + ", ".join(f"{flow(str(k))}: {flow(v)}" for k, v in value.items()) + "}"
    if isinstance(value, list | tuple):
        return "[" + ", ".join(flow(item) for item in value) + "]"
    raise UserError(f"cannot write a {type(value).__name__} to YAML")


def _walk(root: CommentedMap, parts: list[str], key: str) -> tuple[Path_, list[str]]:
    """The (mapping, key) chain to `parts`, and the parts left over when one is missing."""
    found: Path_ = []
    mapping = root
    while parts:
        for size in range(len(parts), 0, -1):
            name = ".".join(parts[:size])
            if name in mapping:
                break
        else:
            return found, parts
        found.append((mapping, name))
        parts = parts[size:]
        if not parts:
            return found, []
        child = mapping[name]
        if not isinstance(child, CommentedMap):
            raise UserError(f"settings: {key} conflicts with {name}")
        mapping = child
    return found, []


def _swap(lines: list[str], mapping: CommentedMap, leaf: str) -> tuple[int, int, int] | None:
    """Line and column span of a one-line scalar value, or None when it spans lines."""
    line, start = mapping.lc.value(leaf)
    if not mapping.fa.flow_style() and _unit(lines, mapping, leaf)[1] != line:
        return None
    end = _scalar_end(lines[line], start, flow_context=mapping.fa.flow_style())
    return None if end is None else (line, start, end)


def _rewrite(lines: list[str], found: Path_, rest: list[str], value: Any, cr: str) -> str:
    """Rewrite the deepest block-mapping entry above the change, on one line ending in
    `cr` (the `\r` of a CRLF text, else empty)."""
    depth = _block_depth(found)
    mapping, name = found[depth]
    plain = _plain(mapping[name])
    path = [key for _, key in found[depth + 1 :]] + rest
    if path:
        node = plain
        for part in path[:-1]:
            node = node.setdefault(part, {})
        node[path[-1]] = value
    else:
        plain = value
    first, last = _unit(lines, mapping, name)
    column = mapping.lc.key(name)[1]
    line, start = mapping.lc.value(name)
    if line == first and isinstance(mapping[name], Mapping | list):  # keep `key:   ` as written
        text = lines[first][:start] + flow(plain)
    else:
        text = " " * column + f"{flow(name)}: {flow(plain)}"
    comment = _comment_at(lines[last])
    if comment is not None:
        text = text.ljust(comment - 1) + " " + lines[last][comment:]
    lines[first : last + 1] = [text.removesuffix("\r") + cr]
    return "\n".join(lines)


def _remove(lines: list[str], found: Path_, cr: str) -> str:
    mapping, name = found[-1]
    if mapping.fa.flow_style():
        depth = _block_depth(found)
        holder, entry = found[depth]
        plain = _plain(holder[entry])
        node = plain
        for _, part in found[depth + 1 : -1]:
            node = node[part]
        del node[name]
        return _rewrite(lines, found[: depth + 1], [], plain, cr)
    if len(mapping) == 1 and len(found) > 1:  # the block would be left empty: drop it too
        return _remove(lines, found[:-1], cr)
    first, last = _unit(lines, mapping, name)
    del lines[first : last + 1]
    return "\n".join(lines)


def _insert(
    lines: list[str], mapping: CommentedMap, key: str, value: Any, cr: str, *, top: bool
) -> str:
    """Add `key: value` after the last entry of a block mapping (top level: file end)."""
    if top:
        if lines and lines[-1] == "":
            lines.pop()
        lines += [f"{flow(key)}: {flow(value)}{cr}", ""]
        return "\n".join(lines)
    last_key = list(mapping)[-1]
    _, last = _unit(lines, mapping, last_key)
    column = mapping.lc.key(last_key)[1]
    lines.insert(last + 1, " " * column + f"{flow(key)}: {flow(value)}{cr}")
    return "\n".join(lines)


def _block_depth(found: Path_) -> int:
    """The index of the deepest entry that sits in a block mapping."""
    blocks = [i for i, (mapping, _) in enumerate(found) if not mapping.fa.flow_style()]
    if not blocks:
        raise UserError("settings: a flow-style file cannot be edited; use key: value lines")
    return blocks[-1]


def _unit(lines: list[str], mapping: CommentedMap, name: str) -> tuple[int, int]:
    """First and last line of a block-mapping entry: its key line and the deeper lines below,
    without trailing blank or comment lines."""
    first, column = mapping.lc.key(name)
    last = first
    for index in range(first + 1, len(lines)):
        stripped = lines[index].strip()
        if not stripped or stripped.startswith("#"):
            continue
        if len(lines[index]) - len(lines[index].lstrip()) <= column:
            break
        last = index
    return first, last


def _scalar_end(line: str, start: int, *, flow_context: bool) -> int | None:
    """Where a scalar starting at `start` ends on `line`; None for a quoted multi-line one."""
    quote = line[start : start + 1]
    if quote in ("'", '"'):
        index = start + 1
        while index < len(line):
            char = line[index]
            if quote == '"' and char == "\\":
                index += 2
                continue
            if char == quote:
                if quote == "'" and line[index + 1 : index + 2] == "'":
                    index += 2
                    continue
                return index + 1
            index += 1
        return None
    index = start
    while index < len(line):
        char = line[index]
        if char == "#" and index > start and line[index - 1] in " \t":
            break
        if flow_context and char in ",}]":
            break
        index += 1
    return len(line[:index].rstrip())


def _comment_at(line: str) -> int | None:
    """The column of `line`'s trailing comment, outside quotes."""
    quote = ""
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = ""
        elif char in ("'", '"'):
            quote = char
        elif char == "#" and (index == 0 or line[index - 1] in " \t"):
            return index
    return None


def _scalar(value: Any) -> bool:
    return not isinstance(value, Mapping | list | tuple)


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, CommentedSeq | list):
        return [_plain(item) for item in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    return str(value)


@cache
def _plain_ok(text: str) -> bool:
    if not _PLAIN.fullmatch(text):
        return False
    return bool(YAML(typ="safe", pure=True).load(text) == text)
