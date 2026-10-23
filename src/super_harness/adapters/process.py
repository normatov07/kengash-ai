"""Run one CLI in its own process group with a timeout; raw output goes to a log file."""

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

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

    stdout goes to `log` and stderr to `log` with suffix `.err`. Background children
    left behind after a normal exit are ended the same way, and so is the whole group when
    the wait is interrupted (a stopped worker), with at most INTERRUPT_GRACE_S.
    """
    log.parent.mkdir(parents=True, exist_ok=True)
    errors = log.with_suffix(".err")
    started = time.monotonic()
    timed_out = False
    with log.open("wb") as out, errors.open("wb") as err:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            start_new_session=True,
        )
        try:
            process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
        except BaseException:  # the caller is being stopped: take the CLI down with it
            _end_group(process, min(grace_s, INTERRUPT_GRACE_S))
            raise
        _end_group(process, grace_s)
    return ProcessResult(
        exit_code=process.returncode,
        stdout=log.read_text(encoding="utf-8", errors="replace"),
        stderr=errors.read_text(encoding="utf-8", errors="replace"),
        timed_out=timed_out,
        duration_s=round(time.monotonic() - started, 3),
    )


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
