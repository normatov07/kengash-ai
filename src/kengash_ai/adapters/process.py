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

INTERRUPT_GRACE_S = 3.0


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_s: float


def run_process(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_s: float,
    log: Path,
    grace_s: float = 10.0,
) -> ProcessResult:
    """Run `argv`; at the timeout, SIGTERM its group, then SIGKILL after `grace_s`.

    stdout goes to `log`, line by line as it arrives, with one ISO-UTC stamp per line in
    `log` with suffix `.ts`; stderr goes to `log` with suffix `.err`. Background children
    left behind after a normal exit are ended the same way, and so is the whole group when
    the wait is interrupted (a stopped worker), with at most INTERRUPT_GRACE_S.
    """
    log.parent.mkdir(parents=True, exist_ok=True)
    errors = log.with_suffix(".err")
    started = time.monotonic()
    timed_out = False
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
        pump = threading.Thread(target=_pump, args=(process.stdout, out, stamps), daemon=True)
        pump.start()
        try:
            process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
        except BaseException:  # the caller is being stopped: take the CLI down with it
            _end_group(process, min(grace_s, INTERRUPT_GRACE_S))
            pump.join(INTERRUPT_GRACE_S)
            raise
        _end_group(process, grace_s)
        pump.join()
    return ProcessResult(
        exit_code=process.returncode,
        stdout=log.read_text(encoding="utf-8", errors="replace"),
        stderr=errors.read_text(encoding="utf-8", errors="replace"),
        timed_out=timed_out,
        duration_s=round(time.monotonic() - started, 3),
    )


def _pump(source: IO[bytes], out: IO[bytes], stamps: IO[str]) -> None:
    """Copy the CLI's stdout to the log as it comes, stamping each line."""
    with source:
        for line in iter(source.readline, b""):
            out.write(line)
            out.flush()
            stamps.write(datetime.now(UTC).isoformat() + "\n")
            stamps.flush()


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
