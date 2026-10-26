"""Start, reuse and stop the UI server (SP5 spec decisions 2 and 3): one detached
`python -m kengash_ai.ui` per store, on 127.0.0.1 and a free port, with a fresh token."""

import contextlib
import importlib.util
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from dataclasses import dataclass

from kengash_ai.model import NeedsSetup, UiRecord, UserError
from kengash_ai.ops import lifecycle
from kengash_ai.store import runtime
from kengash_ai.store.locks import locked
from kengash_ai.store.paths import StorePaths

INSTALL = (
    "install the UI: uv tool install --force "
    "'kengash-ai[ui] @ git+https://github.com/normatov07/kengash-ai'"
)
START_S = 10.0
STOP_S = 5.0


@dataclass
class UiServer:
    url: str
    pid: int
    port: int
    reused: bool


def has_extra() -> bool:
    """FastAPI and uvicorn (the `[ui]` extra) are importable."""
    return all(importlib.util.find_spec(name) is not None for name in ("fastapi", "uvicorn"))


def open_ui(*, browser: bool) -> UiServer:
    """The running server, or a new one; opens the browser on its link unless told not to."""
    paths = StorePaths.default()
    if not paths.home.is_dir():
        raise NeedsSetup("no store yet; run: harness init")
    if not has_extra():
        raise NeedsSetup(INSTALL)
    with locked(paths.locks / "ui.lock"):
        record = runtime.load_ui(paths)
        if record is not None and lifecycle.pid_alive(record.pid) and _answers(record.port):
            server = UiServer(_url(record), record.pid, record.port, reused=True)
        else:
            record = _start(paths)
            server = UiServer(_url(record), record.pid, record.port, reused=False)
    if browser:
        webbrowser.open(server.url)
    return server


def stop_ui() -> bool:
    """End the running server; False when none was running."""
    paths = StorePaths.default()
    with locked(paths.locks / "ui.lock"):
        record = runtime.load_ui(paths)
        runtime.drop_ui(paths)
        if record is None or not lifecycle.pid_alive(record.pid):
            return False
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(record.pid, signal.SIGTERM)
        deadline = time.monotonic() + STOP_S
        while lifecycle.pid_alive(record.pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        return True


def _start(paths: StorePaths) -> UiRecord:
    port = _free_port()
    token = secrets.token_urlsafe(32)
    paths.logs.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, HARNESS_UI_TOKEN=token)
    with (paths.logs / "ui.log").open("ab") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "kengash_ai.ui", "--port", str(port)],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
        )
    record = UiRecord(pid=process.pid, port=port, token=token)
    runtime.save_ui(paths, record)
    deadline = time.monotonic() + START_S
    while not _answers(port):
        if process.poll() is not None or time.monotonic() >= deadline:
            if process.poll() is None:  # alive but silent: end it rather than orphan it
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            runtime.drop_ui(paths)
            raise UserError(f"the UI did not start; log: {paths.logs / 'ui.log'}")
        time.sleep(0.05)
    return record


def _url(record: UiRecord) -> str:
    return f"http://127.0.0.1:{record.port}/?token={record.token}"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _answers(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.2)
        return probe.connect_ex(("127.0.0.1", port)) == 0
