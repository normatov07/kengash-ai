"""Run one CLI in its own process group with a timeout; raw output goes to a log file, each
stdout line stamped in `<log>.ts` as it arrives (SP12: workers can be watched live)."""

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

from kengash_ai.adapters.watchdog import Observer

INTERRUPT_GRACE_S = 3.0
TICK_S = 0.25  # how often a watched call is asked whether it should stop


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_s: float
    stopped: str = ""  # why the observer ended the call; "" when it did not (SP17)


def run_process(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_s: float,
    log: Path,
    grace_s: float = 10.0,
    observe: Observer | None = None,
) -> ProcessResult:
    """Run `argv`; at the timeout, SIGTERM its group, then SIGKILL after `grace_s`.

    stdout goes to `log`, line by line as it arrives, with one ISO-UTC stamp per line in
    `log` with suffix `.ts`; stderr goes to `log` with suffix `.err`. Background children
    left behind after a normal exit are ended the same way, and so is the whole group when
    the wait is interrupted (a stopped worker), with at most INTERRUPT_GRACE_S. `observe`
    sees each stdout line as it comes, and can end the call early with a reason (SP17).
    """
    log.parent.mkdir(parents=True, exist_ok=True)
    errors = log.with_suffix(".err")
    started = time.monotonic()
    timed_out = False
    halt = _Halt()
    with (
        log.open("wb") as out,
        log.with_suffix(".ts").open("w") as stamps,
        errors.open("wb") as err,
    ):
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=err,
            start_new_session=True,
        )
        if process.stdout is None:  # cannot happen with stdout=PIPE; keeps the types honest
            raise OSError("no stdout pipe")
        pump = threading.Thread(
            target=_pump, args=(process.stdout, out, stamps, observe, halt), daemon=True
        )
        pump.start()
        try:
            _wait(process, timeout_s, started, observe, halt)
        except subprocess.TimeoutExpired:
            timed_out = True
        except BaseException:  # the caller is being stopped: take the CLI down with it
            _end_group(process, min(grace_s, INTERRUPT_GRACE_S))
            pump.join(INTERRUPT_GRACE_S)
            raise
        _end_group(process, grace_s)
        # a child that left the group may hold stdout open: never wait on it for long
        pump.join(grace_s)
    return ProcessResult(
        exit_code=process.returncode,
        stdout=log.read_text(encoding="utf-8", errors="replace"),
        stderr=errors.read_text(encoding="utf-8", errors="replace"),
        timed_out=timed_out,
        duration_s=round(time.monotonic() - started, 3),
        stopped=halt.reason,
    )


class _Halt:
    """The observer's reason to end the call, set once by whichever thread sees it first."""

    def __init__(self) -> None:
        self.reason = ""
        self.event = threading.Event()

    def set(self, reason: str) -> None:
        if reason and not self.reason:
            self.reason = reason
            self.event.set()


def _wait(
    process: subprocess.Popen[bytes],
    timeout_s: float,
    started: float,
    observe: Observer | None,
    halt: _Halt,
) -> None:
    """Return when the process exits or the observer ends it; TimeoutExpired at the timeout."""
    if observe is None:
        process.wait(timeout=timeout_s)
        return
    while not halt.event.is_set():
        elapsed = time.monotonic() - started
        if elapsed >= timeout_s:
            raise subprocess.TimeoutExpired(process.args, timeout_s)
        halt.set(observe.tick(elapsed))
        try:
            process.wait(timeout=min(TICK_S, timeout_s - elapsed))
            return
        except subprocess.TimeoutExpired:
            continue


def _pump(
    source: IO[bytes],
    out: IO[bytes],
    stamps: IO[str],
    observe: Observer | None = None,
    halt: _Halt | None = None,
) -> None:
    """Copy the CLI's stdout to the log as it comes, each line's stamp first, so a reader
    never sees a line without its time; stops quietly once the log is closed (a call that
    gave up on a child holding stdout)."""
    with source:
        for line in iter(source.readline, b""):
            try:
                stamps.write(datetime.now(UTC).isoformat() + "\n")
                stamps.flush()
                out.write(line)
                out.flush()
            except (ValueError, OSError):
                return
            if observe is not None and halt is not None and not halt.reason:
                halt.set(_answer(observe, line))


def _answer(observe: Observer, line: bytes) -> str:
    """The observer's verdict on `line`. One that breaks says nothing: a dead pump would leave
    the CLI blocked on a full pipe, and the call still has its hard timeout."""
    try:
        return observe.feed(line.decode("utf-8", errors="replace"))
    except Exception:
        return ""


def _end_group(process: subprocess.Popen[bytes], grace_s: float) -> None:
    """SIGTERM every process in the group; SIGKILL whatever is left after `grace_s`."""
    group = process.pid
    if _signal(group, signal.SIGTERM):
        deadline = time.monotonic() + grace_s
        while process.poll() is None or _signal(group, 0):
            if time.monotonic() >= deadline:
                _signal(group, signal.SIGKILL)
                break
            time.sleep(0.05)
    process.wait()


def _signal(group: int, signum: int) -> bool:
    """Send `signum` to the group; False when no process is left in it."""
    try:
        os.killpg(group, signum)
    except (ProcessLookupError, PermissionError):
        return False
    return True
