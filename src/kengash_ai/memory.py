"""MEMORY.md and DECISIONS.md: one-line facts, capped, redacted and journaled (spec §4.5);
compaction results are checked and applied here (SP3 spec decision 31)."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from kengash_ai import journal, settings
from kengash_ai.model import Event, NeedsSetup, UserError
from kengash_ai.store import storegit
from kengash_ai.store.files import atomic_write
from kengash_ai.store.locks import locked
from kengash_ai.store.paths import StorePaths
from kengash_ai.store.redact import redact

SECTIONS = ("Working style", "Goals", "Preferences", "Turned down")
DECISIONS_CAP = 300
ARCHIVE_HEADER = (
    "# DECISIONS archive\n\n"
    "Entries moved out of DECISIONS.md once it passed 300 lines, oldest first. "
    "Never loaded automatically.\n\n"
)
MAX_WORDS = 30
# the `## Memory` block of a new worker session (SP16 spec §3.1): characters per part
DIGEST_CAPS = {"PROCESS.md": 3_000, "DECISIONS.md": 2_500, "MEMORY.md": 1_500}
_TAG = re.compile(r"^- \d{4}-\d{2}-\d{2} \[([^\]]+)\] ")


@dataclass
class AddResult:
    file: str
    line: str
    lines: int
    cap: int
    added: bool
    compacting: bool = False  # set by ops when the add started a compaction

    @property
    def over_cap(self) -> bool:
        return self.lines > self.cap


def add(
    paths: StorePaths,
    text: str,
    why: str,
    *,
    section: str = "Preferences",
    decision: bool = False,
    rejected: str | None = None,
    project: str | None = None,
    by: str = "unknown",
) -> AddResult:
    """Record one fact in MEMORY.md (under `section`) or one decision in DECISIONS.md."""
    if not paths.memory.is_dir():
        raise NeedsSetup("no store yet; run: kengash init")
    fact, reason = _one_line(text), _one_line(why)
    if decision:
        name, cap = "DECISIONS.md", DECISIONS_CAP
        entry = f"- {date.today().isoformat()} [{project or 'global'}] {fact.rstrip('.')}."
        entry += f" why: {reason.rstrip('.')}."
        if rejected:
            entry += f" rejected: {_one_line(rejected).rstrip('.')}."
    else:
        if section not in SECTIONS:
            raise UserError(f"unknown section {section!r}; use one of: {', '.join(SECTIONS)}")
        # MEMORY.md is global, so its cap comes from the user's defaults, not a project's file.
        name, cap = "MEMORY.md", settings.load(paths).memory.compact_at_lines
        entry = f"- {fact}"
    entry = redact(entry)
    path = paths.memory / name
    with locked(paths.locks / "memory.lock"):
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        if entry in lines:
            return AddResult(name, entry, len(lines), cap, added=False)
        lines = [*lines, entry] if decision else _insert(lines, section, entry)
        moved: list[str] = []
        if decision:
            lines, moved = archive_oldest(lines, cap)
            if moved:
                _archive(paths, moved)
        atomic_write(path, "\n".join(lines) + "\n")
    detail: dict[str, Any] = {
        "type": "memory.write",
        "project": project,
        "file": name,
        "line": entry,
        "why": reason,
        "by": by,
    }
    if not decision:
        detail["section"] = section
    if moved:
        detail["archived"] = len(moved)
    journal.append(paths, Event.model_validate(detail))
    storegit.commit_store(paths, f"kengash: memory add {name}")
    return AddResult(name, entry, len(lines), cap, added=True)


@dataclass
class Compaction:
    """A compaction result: the line counts, and why it was rejected."""

    before: int
    after: int
    accepted: bool
    reason: str = ""


def compaction_problem(current: list[str], result: list[str], cap: int) -> str | None:
    """Why `result` may not replace MEMORY.md, or None: it must not be empty, must keep every
    entry marked (pin) and every heading of `current`, and must stay under `cap` lines."""
    kept = {line.strip() for line in result}
    if not any(kept):
        return "the result is empty"
    pins = [line for line in current if _pinned(line) and line.strip() not in kept]
    if pins:
        return f"the result drops {len(pins)} pinned line(s): {pins[0].strip()}"
    headings = [line for line in current if line.startswith("## ") and line.strip() not in kept]
    if headings:
        return f"the result drops the heading {headings[0].strip()}"
    if len(result) >= cap:
        return f"the result has {len(result)} lines; the cap is {cap}"
    return None


def merge_added(snapshot: list[str], current: list[str], result: list[str]) -> list[str]:
    """`result` plus the entries written to `current` since `snapshot`, each in its section."""
    seen = set(snapshot)
    merged = list(result)
    section: str | None = None
    for line in current:
        if line.startswith("## "):
            section = line[3:]
        elif line.startswith("- ") and line not in seen and line not in merged:
            merged = _insert(merged, section, line) if section else [*merged, line]
    return merged


def apply_compaction(
    paths: StorePaths, snapshot: str, text: str, *, cap: int, detail: Mapping[str, Any]
) -> Compaction:
    """Replace MEMORY.md with a compacted `text` (taken from `snapshot`) once it passes
    `compaction_problem`; journal `memory.compacted` either way."""
    path = paths.memory / "MEMORY.md"
    result = redact(text).strip("\n").splitlines()
    with locked(paths.locks / "memory.lock"):
        current = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        merged = merge_added(snapshot.splitlines(), current, result)
        problem = compaction_problem(current, merged, cap)
        outcome = Compaction(len(current), len(merged), problem is None, problem or "")
        if outcome.accepted:
            atomic_write(path, "\n".join(merged) + "\n")
    event = {
        "type": "memory.compacted",
        "file": "MEMORY.md",
        "before": outcome.before,
        "after": outcome.after,
        "accepted": outcome.accepted,
        "reason": problem,
        **detail,
        "by": "kengash",
    }
    journal.append(paths, Event.model_validate(event))
    if outcome.accepted:
        storegit.commit_store(paths, "kengash: memory compact")
    return outcome


def show(paths: StorePaths, *, decisions: bool = False, project: str | None = None) -> str:
    """MEMORY.md, or DECISIONS.md narrowed to one project's and the global entries."""
    path = paths.memory / ("DECISIONS.md" if decisions else "MEMORY.md")
    if not path.exists():
        raise NeedsSetup("no store yet; run: kengash init")
    text = path.read_text(encoding="utf-8")
    if not (decisions and project):
        return text
    tags = (f"[{project}]", "[global]")
    kept = [
        line
        for line in text.splitlines()
        if not line.startswith("- ") or any(tag in line for tag in tags)
    ]
    return "\n".join(kept) + "\n"


def digest(paths: StorePaths, project: str | None) -> str:
    """What every new worker session is told to follow (SP16 spec §3.1): the head of the
    project's process notes, the newest of its and the global decisions, and the newest of
    the user's memory, each within its cap; redacted, and "" when there is nothing."""
    parts = [
        _part("Process (PROCESS.md)", _process_lines(paths, project), "PROCESS.md", newest=False),
        _part(
            "Decisions (DECISIONS.md, newest last)", _decision_lines(paths, project), "DECISIONS.md"
        ),
        _part("Preferences (MEMORY.md)", _memory_lines(paths), "MEMORY.md"),
    ]
    return redact("\n\n".join(part for part in parts if part))


def _part(title: str, lines: list[str], name: str, *, newest: bool = True) -> str:
    """`title` and the `lines` that fit `name`'s cap: the newest (last) ones, or the first."""
    if not lines:
        return ""
    kept: list[str] = []
    size = 0
    for line in reversed(lines) if newest else lines:
        if size + len(line) + 1 > DIGEST_CAPS[name]:
            break
        kept.append(line)
        size += len(line) + 1
    dropped = len(lines) - len(kept)
    if newest:
        body = [*([f"… {dropped} older lines in {name}"] if dropped else []), *reversed(kept)]
    else:
        body = [*kept, *([f"… {dropped} more lines in {name}"] if dropped else [])]
    return "\n".join([f"{title}:", *body])


def _process_lines(paths: StorePaths, project: str | None) -> list[str]:
    """PROCESS.md from its first `## ` heading, blank lines dropped; [] when only headings."""
    path = paths.project(project).process if project else None
    if path is None or not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("## ")), len(lines))
    body = [line for line in lines[start:] if line.strip()]
    return body if any(not line.startswith("#") for line in body) else []


def _decision_lines(paths: StorePaths, project: str | None) -> list[str]:
    """DECISIONS.md entries tagged with `project` or `global`, oldest first."""
    path = paths.memory / "DECISIONS.md"
    if not path.exists():
        return []
    tags = {"global", *([project] if project else [])}
    return [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if (found := _TAG.match(line)) and found.group(1) in tags
    ]


def _memory_lines(paths: StorePaths) -> list[str]:
    """MEMORY.md entries as `- [<section>] <text>`, in file order."""
    path = paths.memory / "MEMORY.md"
    if not path.exists():
        return []
    section, found = "", []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
        elif line.startswith("- "):
            found.append(f"- [{section}] {line[2:]}" if section else line)
    return found


def archive_oldest(lines: list[str], cap: int) -> tuple[list[str], list[str]]:
    """Split off the oldest `- ` entries that take `lines` past `cap`: (kept, moved)."""
    excess = len(lines) - cap
    kept: list[str] = []
    moved: list[str] = []
    for line in lines:
        if len(moved) < excess and line.startswith("- "):
            moved.append(line)
        else:
            kept.append(line)
    return kept, moved


def _archive(paths: StorePaths, entries: list[str]) -> None:
    """Append `entries` to memory/archive/DECISIONS.md (caller holds memory.lock)."""
    path = paths.memory / "archive" / "DECISIONS.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.exists() else ARCHIVE_HEADER
    atomic_write(path, text + "".join(f"{entry}\n" for entry in entries))


def _pinned(line: str) -> bool:
    return line.startswith("- ") and "(pin)" in line


def _one_line(text: str) -> str:
    value = text.strip()
    if not value:
        raise UserError("memory text is empty")
    if len(value.splitlines()) > 1:
        raise UserError("memory text must be one line")
    if len(value.split()) > MAX_WORDS:
        raise UserError(f"keep memory lines under {MAX_WORDS} words (aim for 20)")
    return value


def _insert(lines: list[str], section: str, entry: str) -> list[str]:
    """Append `entry` to `section`, keeping one blank line after the heading and before the next."""
    heading = f"## {section}"
    if heading not in lines:
        return [*lines, "", heading, "", entry]
    start = lines.index(heading) + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    entries = [line for line in lines[start:end] if line.strip()]
    tail = [""] if end < len(lines) else []
    return [*lines[:start], "", *entries, entry, *tail, *lines[end:]]
