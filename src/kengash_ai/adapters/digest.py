"""A failing check's output cut down to what says what broke (SP15 spec §3.2).

Framework-agnostic: marker lines (errors, failures, expected/actual values, analyzer rows,
`path:line` references) with a little context, the runner's closing summary, and nothing
else; the full output stays in the log the digest names.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

BEFORE = 2  # context lines kept before a marker
AFTER = 8  # and after it
TAIL = 2  # last non-empty lines always kept: the runner's summary
MAX_LINES = 60
MAX_CHARS = 4000
LINE_CHARS = 300
HEADLINE_CHARS = 160
NO_MARKER_LINES = 30

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_REPEATS = re.compile(r"([^\w\s])\1{3,}")  # ════ rules and ---- bars shrink to three
# Whole marker words; `error` and `exception` also end longer names (TypeError). Every
# pattern starts at a token boundary, so a long line costs linear time.
_WORDS = (
    r"(?:error|exception)s?\b|\b(?:fail(?:s|ed|ure|ures)?|traceback|assert(?:ion)?"
    r"|expected|actual|panic(?:ked)?|undefined|cannot|can't|not found)\b"
)
_MARKER = re.compile(
    rf"{_WORDS}|\[E\]|✗|✘|^\s*(?:info|warning|error) •|(?<![\w./~-])[\w./~-]+\.\w+:\d+",
    re.IGNORECASE,
)
# Runner lines that only say what failed, preferred for the headline.
_STRONG = re.compile(
    r"\[E\]|✗|✘|\bFAIL(?:ED|URES?)?\b|\bERROR\b|EXCEPTION|Traceback|^\s*Expected:"
    r"|\bError:|^E\s|^\s*(?:info|warning|error) •"
)
# A dart/flutter test progress line names the running test; its name is no marker.
_PROGRESS = re.compile(r"^\d+:\d+ \+\d+(?: ~\d+)?(?: -\d+)?: ")
_LOCATION = re.compile(r"(?<![\w./~-])([\w./~-]+\.\w+):(\d+)")


@dataclass(frozen=True)
class Digest:
    headline: str
    text: str
    file: str = ""
    line: int = 0


def excerpt(output: str, *, command: str, exit_code: int, cwd: Path, log: Path) -> Digest:
    """The digest of a check that exited `exit_code`; `cwd` is the worktree it ran in."""
    lines = [_clean(line) for line in output.splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    markers = [index for index, line in enumerate(lines) if _marker(line)]
    if markers:
        kept = _windows(markers, len(lines))
        strong = next((i for i in markers if _STRONG.search(lines[i])), markers[0])
        first = lines[strong].strip()
    else:
        kept = list(range(max(len(lines) - NO_MARKER_LINES, 0), len(lines)))
        first = lines[-1].strip() if lines else ""
    tail = [index for index, line in enumerate(lines) if line.strip()][-TAIL:]
    body, dropped = _capped([index for index in kept if index not in tail], tail, lines)
    chosen = body + tail
    text = [lines[index] for index in body]
    if dropped:  # before the summary, so the runner's last words stay last
        text.append(f"… {dropped} more {'line' if dropped == 1 else 'lines'}; full output: {log}")
    text += [lines[index] for index in tail]
    headline = f"`{command}` exit {exit_code}" + (f": {first[:HEADLINE_CHARS]}" if first else "")
    file, line = _location((lines[index] for index in chosen), cwd)
    return Digest(headline, "\n".join(text), file, line)


def section(digest: Digest) -> str:
    """The `## Check output` body: the headline, then the digest in a fenced block."""
    body = "\n".join(
        f" {line}" if line.startswith("```") else line for line in digest.text.split("\n")
    )
    return f"{digest.headline}\n```text\n{body}\n```"


def _marker(line: str) -> bool:
    if _PROGRESS.match(line):
        return "[E]" in line
    return _MARKER.search(line) is not None


def _clean(line: str) -> str:
    return _REPEATS.sub(r"\1\1\1", _ANSI.sub("", line)).rstrip()[:LINE_CHARS]


def _windows(markers: list[int], count: int) -> list[int]:
    """Each marker with its context, merged, in order."""
    kept: set[int] = set()
    for index in markers:
        kept.update(range(max(index - BEFORE, 0), min(index + AFTER + 1, count)))
    return sorted(kept)


def _capped(body: list[int], tail: list[int], lines: list[str]) -> tuple[list[int], int]:
    """The earliest body lines that fit beside the tail (and the overflow note), and how many
    were left out."""
    room_lines = MAX_LINES - len(tail) - 1
    room_chars = MAX_CHARS - sum(len(lines[index]) + 1 for index in tail)
    taken: list[int] = []
    for index in body:
        cost = len(lines[index]) + 1
        if len(taken) >= room_lines or cost > room_chars:
            break
        taken.append(index)
        room_chars -= cost
    return taken, len(body) - len(taken)


def _location(lines: Iterable[str], cwd: Path) -> tuple[str, int]:
    """The first `path:line` that names a file inside `cwd`, relative to it."""
    root = cwd.resolve()
    for line in lines:
        for match in _LOCATION.finditer(line):
            raw = match.group(1)
            path = Path("/" + raw.lstrip("/")) if raw.startswith("/") else Path(raw)
            try:
                relative = path.resolve().relative_to(root) if path.is_absolute() else path
            except ValueError:
                continue
            if (root / relative).is_file():
                return relative.as_posix(), int(match.group(2))
    return "", 0
