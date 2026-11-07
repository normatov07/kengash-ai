"""Opening a viewer in a new terminal tab (SP13 spec §3.2): Orca, tmux, gnome-terminal, or
the user's own command template. Nothing here raises: a tab that cannot open is reported
as not opened, and the caller prints the command instead."""

import contextlib
import shlex
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

OPEN_WAIT_S = 5.0  # how long `run` waits to learn whether a tab opened
OFF = "KENGASH_WATCH"  # "off" turns every tab and notification off (tests, evals, CI)

type Which = Callable[[str], str | None]


@dataclass(frozen=True)
class Terminal:
    """`name` for messages; `argv(title, command)` is the command that opens the tab."""

    name: str
    argv: Callable[[str, list[str]], list[str]]


def disabled(env: Mapping[str, str]) -> bool:
    """Tabs and notifications are off in this environment."""
    return env.get(OFF, "").strip().lower() in ("off", "0", "false", "no")


def detect(env: Mapping[str, str], template: str, which: Which = shutil.which) -> Terminal | None:
    """The terminal a tab opens in, from the opener's environment; None when there is none."""
    if template.strip():
        return Terminal("custom", lambda title, cmd: _templated(template, title, cmd))
    if env.get("TERM_PROGRAM") == "Orca" and which("orca"):
        return Terminal("orca", _orca)
    if env.get("TMUX") and which("tmux"):
        return Terminal("tmux", _tmux)
    if (env.get("DISPLAY") or env.get("WAYLAND_DISPLAY")) and which("gnome-terminal"):
        return Terminal("gnome-terminal", _gnome)
    return None


def open_tab(terminal: Terminal, title: str, command: list[str], *, cwd: Path) -> bool:
    """Start the terminal's opener, detached. True once it exits 0, or while it still runs
    after OPEN_WAIT_S: some openers (`xterm -e`, a template) run as long as their window,
    and are never killed."""
    with contextlib.suppress(OSError, subprocess.SubprocessError, ValueError):
        proc = subprocess.Popen(
            terminal.argv(title, command),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            return proc.wait(timeout=OPEN_WAIT_S) == 0
        except subprocess.TimeoutExpired:
            return True
    return False


def _templated(template: str, title: str, command: list[str]) -> list[str]:
    filled = template.replace("{title}", shlex.quote(title)).replace(
        "{command}", shlex.join(command)
    )
    return ["sh", "-c", filled]


def _orca(title: str, command: list[str]) -> list[str]:
    return [
        "orca",
        "terminal",
        "create",
        "--title",
        title,
        "--command",
        shlex.join(command),
        "--json",
    ]


def _tmux(title: str, command: list[str]) -> list[str]:
    return ["tmux", "new-window", "-d", "-n", title, shlex.join(command)]


def _gnome(title: str, command: list[str]) -> list[str]:
    return ["gnome-terminal", "--tab", f"--title={title}", "--", *command]
