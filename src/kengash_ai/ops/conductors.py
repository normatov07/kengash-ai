"""Who is calling kengash: the conductor process, an agent CLI or a terminal (SP3 spec
decision 33; SP11 spec §4.1)."""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

AGENTS = ("claude", "codex", "agy")
ANCESTORS = 20


@dataclass(frozen=True)
class Conductor:
    """The process a lease or ping belongs to."""

    pid: int
    agent: str  # $KENGASH_AGENT, $HARNESS_AGENT, the detected name, else "unknown"
    command: str  # the process name at `pid`; "" when ps cannot tell
    detected: bool  # found as an ancestor named claude, codex or agy


def conductor() -> Conductor:
    """The nearest ancestor process named claude, codex or agy, else the parent."""
    parent = os.getppid()
    pid, detected = parent, None
    for _ in range(ANCESTORS):
        if pid <= 1:
            break
        found = _ps(pid)
        if found is None:
            break
        ppid, command = found
        if Path(command).name in AGENTS:
            detected = Path(command).name
            break
        pid = ppid
    if detected is None:
        pid = parent
    agent = (
        os.environ.get("KENGASH_AGENT") or os.environ.get("HARNESS_AGENT") or detected or "unknown"
    )
    return Conductor(pid, agent, process_name(pid) or "", detected is not None)


def process_name(pid: int) -> str | None:
    """The name `ps` gives `pid`, without its folder; None when no such process runs."""
    found = _ps(pid)
    return Path(found[1]).name if found else None


def _ps(pid: int) -> tuple[int, str] | None:
    """`pid`'s parent and command name, or None."""
    try:
        result = subprocess.run(
            ["ps", "-o", "ppid=,comm=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    fields = result.stdout.strip().split(None, 1)
    if result.returncode != 0 or len(fields) != 2 or not fields[0].isdigit():
        return None
    return int(fields[0]), fields[1].strip()
