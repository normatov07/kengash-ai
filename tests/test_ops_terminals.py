"""Terminal detection and tab commands (SP13 spec §3.2)."""

import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from kengash_ai.ops import terminals

CMD = ["kengash", "logs", "7add8c2e", "--watch"]


def found(*names: str) -> Callable[[str], str | None]:
    return lambda name: f"/usr/bin/{name}" if name in names else None


def test_a_template_wins_and_quotes_the_command() -> None:
    term = terminals.detect(
        {"TERM_PROGRAM": "Orca", "TMUX": "x"}, "kitty @ launch --title {title} {command}", found()
    )
    assert term is not None and term.name == "custom"
    argv = term.argv("kg 7add8c2e", CMD)
    assert argv == [
        "sh",
        "-c",
        "kitty @ launch --title 'kg 7add8c2e' kengash logs 7add8c2e --watch",
    ]


def test_orca_needs_its_terminal_and_its_cli() -> None:
    term = terminals.detect({"TERM_PROGRAM": "Orca"}, "", found("orca"))
    assert term is not None and term.name == "orca"
    assert term.argv("kg 7add8c2e", CMD) == [
        "orca",
        "terminal",
        "create",
        "--title",
        "kg 7add8c2e",
        "--command",
        "kengash logs 7add8c2e --watch",
        "--json",
    ]
    assert terminals.detect({"TERM_PROGRAM": "Orca"}, "", found()) is None


def test_tmux_by_its_variable() -> None:
    term = terminals.detect({"TMUX": "tmux-socket,1,0"}, "", found("tmux"))
    assert term is not None and term.name == "tmux"
    assert term.argv("kg 7add8c2e", CMD) == [
        "tmux",
        "new-window",
        "-d",
        "-n",
        "kg 7add8c2e",
        "kengash logs 7add8c2e --watch",
    ]


def test_gnome_terminal_needs_a_display() -> None:
    term = terminals.detect({"WAYLAND_DISPLAY": "wayland-0"}, "", found("gnome-terminal"))
    assert term is not None and term.name == "gnome-terminal"
    assert term.argv("kg 7add8c2e", CMD) == [
        "gnome-terminal",
        "--tab",
        "--title=kg 7add8c2e",
        "--",
        *CMD,
    ]
    assert terminals.detect({}, "", found("gnome-terminal")) is None


def test_nothing_found() -> None:
    assert terminals.detect({"DISPLAY": ":0"}, "", found()) is None


def test_open_tab_never_raises(tmp_path: Path) -> None:
    missing = terminals.Terminal("x", lambda title, cmd: ["/no/such/terminal", title])
    assert terminals.open_tab(missing, "t", CMD, cwd=tmp_path) is False
    failing = terminals.Terminal("x", lambda title, cmd: [sys.executable, "-c", "exit(3)"])
    assert terminals.open_tab(failing, "t", CMD, cwd=tmp_path) is False
    working = terminals.Terminal("x", lambda title, cmd: [sys.executable, "-c", "pass"])
    assert terminals.open_tab(working, "t", CMD, cwd=tmp_path) is True


def test_open_tab_gives_up_on_a_hanging_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(terminals, "OPEN_TIMEOUT_S", 0.5)
    hanging = terminals.Terminal(
        "x", lambda title, cmd: [sys.executable, "-c", "import time; time.sleep(30)"]
    )
    assert terminals.open_tab(hanging, "t", CMD, cwd=tmp_path) is False  # caught, not raised
