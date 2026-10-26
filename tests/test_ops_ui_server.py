"""`kengash ui open|stop`: one detached server per store, reused while it lives
(SP5 spec decisions 2 and 3)."""

import json
import subprocess
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from typer.testing import CliRunner

from kengash_ai.cli import app
from kengash_ai.model import UserError
from kengash_ai.ops import ui_server
from kengash_ai.store import StorePaths

runner = CliRunner()


@pytest.fixture
def stopped(registered_repo: Path) -> Iterator[None]:
    yield
    ui_server.stop_ui()


def get_overview(url: str) -> dict[str, object]:
    parts = urlparse(url)
    token = parse_qs(parts.query)["token"][0]
    request = urllib.request.Request(
        f"http://{parts.netloc}/api/overview", headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return dict(json.loads(response.read()))


def test_open_starts_reuses_and_stop_ends_the_server(
    stopped: None, store_paths: StorePaths
) -> None:
    first = ui_server.open_ui(browser=False)
    assert first.url.startswith("http://127.0.0.1:") and not first.reused
    assert get_overview(first.url)["projects"] == ["payments-api"]
    assert (store_paths.ui_file.stat().st_mode & 0o777) == 0o600
    again = ui_server.open_ui(browser=False)
    assert (again.url, again.reused) == (first.url, True)
    assert ui_server.stop_ui() is True
    assert ui_server.stop_ui() is False


def test_a_stale_record_starts_a_new_server(stopped: None, store_paths: StorePaths) -> None:
    store_paths.ui_file.parent.mkdir(parents=True, exist_ok=True)
    stale = {"pid": 2**22 + 7, "port": 1, "token": "x", "started": "2026-10-23T00:00:00Z"}
    store_paths.ui_file.write_text(json.dumps(stale))
    server = ui_server.open_ui(browser=False)
    assert not server.reused and get_overview(server.url)["sessions"] == []


def test_a_server_that_never_answers_is_ended(
    stopped: None, store_paths: StorePaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[subprocess.Popen[bytes]] = []
    popen = subprocess.Popen

    def spy(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        started.append(popen(*args, **kwargs))
        return started[-1]

    monkeypatch.setattr(subprocess, "Popen", spy)
    monkeypatch.setattr(ui_server, "_answers", lambda port: False)
    monkeypatch.setattr(ui_server, "START_S", 0.5)
    with pytest.raises(UserError, match="did not start"):
        ui_server.open_ui(browser=False)
    assert started[0].poll() is not None and not store_paths.ui_file.exists()


def test_the_cli_opens_and_stops(stopped: None) -> None:
    opened = runner.invoke(app, ["ui", "open", "--no-browser"])
    assert opened.exit_code == 0 and opened.stdout.startswith("http://127.0.0.1:")
    assert runner.invoke(app, ["ui", "stop"]).stdout == "stopped\n"
    assert runner.invoke(app, ["ui", "stop"]).stdout == "not running\n"


def test_without_the_extra_open_names_the_install(
    registered_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ui_server, "has_extra", lambda: False)
    result = runner.invoke(app, ["ui", "open", "--no-browser"])
    assert result.exit_code == 4 and "kengash-ai[ui]" in result.stderr
