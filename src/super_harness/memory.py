"""MEMORY.md and DECISIONS.md: one-line facts, capped, redacted and journaled (spec §4.5)."""

from dataclasses import dataclass
from datetime import date

from super_harness import journal, settings
from super_harness.model import Event, NeedsSetup, UserError
from super_harness.store import storegit
from super_harness.store.files import atomic_write
from super_harness.store.locks import locked
from super_harness.store.paths import StorePaths
from super_harness.store.redact import redact

SECTIONS = ("Working style", "Goals", "Preferences", "Turned down")
DECISIONS_CAP = 300
MAX_WORDS = 30


@dataclass
class AddResult:
    file: str
    line: str
    lines: int
    cap: int
    added: bool

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
        raise NeedsSetup("no store yet; run: harness init")
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
        atomic_write(path, "\n".join(lines) + "\n")
    detail = {
        "type": "memory.write",
        "project": project,
        "file": name,
        "line": entry,
        "why": reason,
        "by": by,
    }
    if not decision:
        detail["section"] = section
    journal.append(paths, Event.model_validate(detail))
    storegit.commit_store(paths, f"harness: memory add {name}")
    return AddResult(name, entry, len(lines), cap, added=True)


def show(paths: StorePaths, *, decisions: bool = False, project: str | None = None) -> str:
    """MEMORY.md, or DECISIONS.md narrowed to one project's and the global entries."""
    path = paths.memory / ("DECISIONS.md" if decisions else "MEMORY.md")
    if not path.exists():
        raise NeedsSetup("no store yet; run: harness init")
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


def _one_line(text: str) -> str:
    value = text.strip()
    if not value:
        raise UserError("memory text is empty")
    if "\n" in value:
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
