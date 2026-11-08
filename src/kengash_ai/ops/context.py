"""Exact context, built by kengash at the moment of use (SP17 spec §3.8).

What kengash can read itself it reads itself: a model's recollection of a file is never passed
on as fact. An implementer's first prompt carries the plan's files as they are on disk now,
so it spends no turns reading them and a path the plan invented shows up at once.
"""

import hashlib
from collections.abc import Sequence
from fnmatch import fnmatch
from pathlib import Path

MAX_FILE_BYTES = 40 * 1024
_SNIFF = 8192


def file_pack(
    worktree: Path, files: Sequence[str], *, commit: str, shared: Sequence[str], budget: int
) -> str:
    """The `## Files` body for `files`, within `budget` bytes; "" when there is nothing to say.

    Directories, generated files (`shared`), binary and oversized files stay out, named so
    the agent can read them. A path with no file is named as new or mistaken. Nothing outside
    the worktree is read, whatever the path or a symlink says."""
    root = worktree.resolve()
    shown: list[str] = []
    left_out: list[str] = []
    absent: list[str] = []
    room = budget
    for name in files:
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            left_out.append(f"{name} (outside the worktree)")
        elif not path.exists():
            absent.append(name)
        elif path.is_dir():
            continue
        elif any(fnmatch(name, pattern) for pattern in shared):
            left_out.append(f"{name} (generated)")
        else:
            entry, why = _entry(name, path)
            if entry and len(entry.encode()) <= room:
                shown.append(entry)
                room -= len(entry.encode())
            else:
                left_out.append(f"{name} ({why or 'over the prompt budget'})")
    return _body(commit, shown, left_out, absent)


def _entry(name: str, path: Path) -> tuple[str, str]:
    """A file's heading and fenced contents, or "" and why it stays out."""
    try:
        data = path.read_bytes()
    except OSError:
        return "", "unreadable"
    if len(data) > MAX_FILE_BYTES:
        return "", "too large"
    if b"\0" in data[:_SNIFF]:
        return "", "binary"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "", "binary"
    blob = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()[:10]  # noqa: S324
    fence = "`" * max(3, _longest_backticks(text) + 1)
    lines = len(text.splitlines())
    return f"### {name} · {lines} lines · blob {blob}\n{fence}\n{text.rstrip(chr(10))}\n{fence}", ""


def _longest_backticks(text: str) -> int:
    longest = current = 0
    for char in text:
        current = current + 1 if char == "`" else 0
        longest = max(longest, current)
    return longest


def _body(commit: str, shown: list[str], left_out: list[str], absent: list[str]) -> str:
    parts: list[str] = []
    if shown:
        parts.append(
            f"The plan's files as they are in this worktree right now (commit {commit}), read by "
            "kengash, not from memory. Do not read them again unless you edit them: once you "
            "edit a file, this copy is out of date."
        )
        parts += shown
    if left_out:
        parts.append("Not shown, read them yourself: " + ", ".join(left_out))
    if absent:
        parts.append(
            f"No such file at {commit}, so new or mistaken: {', '.join(absent)}. "
            "Create one only if the plan calls for it."
        )
    return "\n\n".join(parts)
