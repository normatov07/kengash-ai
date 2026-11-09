"""Notice a CLI call going nowhere while it runs (SP17 spec §3.1).

Pure: each driver maps its stream events to a `Signal`, this counts them, and a non-empty
answer tells the process runner to stop the call. The step loop then resumes the session
with a correction; a headless CLI takes no input in the middle of a turn.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from kengash_ai.adapters import stream

_SEPARATOR = re.compile(r"\s*(?:;|&&|\|\||\|)\s*")  # between the commands of one line
_REDIRECT = re.compile(r"\s+\d?>.*$")


@dataclass(frozen=True)
class Signal:
    """What one stream event says the agent did: `run` carries the command."""

    kind: Literal["edit", "poll", "run"]
    command: str = ""


class Observer(Protocol):
    """What the process runner asks; an empty answer lets the call go on."""

    def feed(self, line: str) -> str: ...
    def tick(self, elapsed: float) -> str: ...


class Watchdog:
    """One call's counters. `poll_max` and `full_runs_max` of 0 switch that rule off."""

    def __init__(
        self,
        signal: Callable[[dict[str, Any]], Signal | None],
        *,
        soft_s: int,
        poll_max: int,
        full_runs_max: int,
        test_cmd: str,
    ) -> None:
        self._signal = signal
        self._soft_s = soft_s
        self._poll_max = poll_max
        self._full_runs_max = full_runs_max
        self._test_cmd = test_cmd.strip()
        self._polls = 0
        self._full_runs = 0

    def feed(self, line: str) -> str:
        """Why the call must stop after `line`; "" while it may go on."""
        for event in stream.lines(line):
            found = self._signal(event)
            if found is not None:
                return self._count(found)
        return ""

    def tick(self, elapsed: float) -> str:
        """Why the call must stop `elapsed` seconds in; "" while it may go on."""
        if elapsed >= self._soft_s:
            return f"{self._soft_s // 60} minutes have passed in this turn"
        return ""

    def _count(self, found: Signal) -> str:
        if found.kind == "edit":
            self._polls = 0
        elif found.kind == "poll":
            self._polls += 1
            if self._poll_max and self._polls >= self._poll_max:
                return f"you made {self._polls} polls of a background command with no edit"
        elif self._whole_suite(found.command):
            self._full_runs += 1
            if self._full_runs_max and self._full_runs > self._full_runs_max:
                return f"you ran the whole test suite {self._full_runs} times in this turn"
        return ""

    def _whole_suite(self, command: str) -> bool:
        """The project's test command anywhere in the line: alone, wrapped in a shell, or
        beside other commands, pipes and redirects."""
        if not self._test_cmd:
            return False
        said = command.strip()
        wanted = (f" {self._test_cmd}", f"'{self._test_cmd}", f'"{self._test_cmd}')
        pieces = (_REDIRECT.sub("", piece) for piece in _SEPARATOR.split(said))
        return any(
            form.strip("'\"") == self._test_cmd or form.rstrip("'\"").endswith(wanted)
            for form in (said, *pieces)
        )
