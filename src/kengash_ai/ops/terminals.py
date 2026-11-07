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

OPEN_TIMEOUT_S = 10.0

type Which = Callable[[str], str | None]


@dataclass(frozen=True)
class Terminal:
    """`name` for messages; `argv(title, command)` is the command that opens the tab."""

    name: str
    argv: Callable[[str, list[str]], list[str]]


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
    """Run the terminal's opener; True once it exits 0 within OPEN_TIMEOUT_S."""
    with contextlib.suppress(OSError, subprocess.SubprocessError, ValueError):
        done = subprocess.run(
            terminal.argv(title, command),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=OPEN_TIMEOUT_S,
            check=False,
        )
        return done.returncode == 0
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
