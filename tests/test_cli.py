import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kengash_ai import __version__
from kengash_ai.cli import app

runner = CliRunner()


def test_version_names_the_package() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"kengash-ai {__version__}"


def test_help_lists_the_version_option() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    # Typer forces Rich colours under GITHUB_ACTIONS, so CI help text carries escape codes
    assert "--version" in re.sub(r"\x1b\[[0-9;]*m", "", result.output)


DEPRECATED = "harness is now kengash; the harness and hrn names stop working in 0.3.0\n"


@pytest.mark.parametrize("command", ["kengash", "harness", "hrn"])
def test_console_scripts_print_version(command: str) -> None:
    executable = shutil.which(command)
    assert executable, f"{command} is not on PATH; run `make setup`"
    done = subprocess.run([executable, "--version"], check=True, capture_output=True, text=True)
    assert done.stdout == f"kengash-ai {__version__}\n"
    assert done.stderr == ("" if command == "kengash" else DEPRECATED)


def test_the_old_names_keep_json_clean(registered_repo: Path) -> None:
    hrn = shutil.which("hrn")
    assert hrn
    done = subprocess.run(
        [hrn, "settings", "get", "loop_max", "--json"],
        cwd=registered_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(done.stdout)["critical"] == 6 and done.stderr == DEPRECATED


def test_the_version_is_0_2_0() -> None:
    assert __version__ == "0.2.0"


def test_native_windows_stops_with_the_wsl_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kengash_ai.cli.sys.platform", "win32")
    for args in (["--version"], ["status"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 4
        assert "kengash runs on Linux and macOS; on Windows use WSL" in result.output


def test_the_first_command_moves_a_0_1_store_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("KENGASH_HOME", raising=False)
    monkeypatch.delenv("HARNESS_HOME", raising=False)
    (tmp_path / ".harness").mkdir()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0 and (tmp_path / ".kengash").is_dir()
    assert f"moved {tmp_path / '.harness'} to {tmp_path / '.kengash'}" in result.stderr
