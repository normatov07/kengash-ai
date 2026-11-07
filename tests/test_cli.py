import re
import shutil
import subprocess
import tomllib
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


def test_console_scripts_print_version() -> None:
    executable = shutil.which("kengash")
    assert executable, "kengash is not on PATH; run `make setup`"
    done = subprocess.run([executable, "--version"], check=True, capture_output=True, text=True)
    assert (done.stdout, done.stderr) == (f"kengash-ai {__version__}\n", "")


def test_only_kengash_is_installed() -> None:
    """0.1.0's `harness` and `hrn` warned through 0.2.x and stop in 0.3.0 (SP8 spec decision 1)."""
    root = Path(__file__).resolve().parents[1]
    scripts = tomllib.loads((root / "pyproject.toml").read_text())["project"]["scripts"]
    assert scripts == {"kengash": "kengash_ai.cli:app"}


def test_the_version_is_0_5_0() -> None:
    assert __version__ == "0.5.0"


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


def test_every_command_help_renders() -> None:
    """Rich reads `[...]` in help text as markup; a stray one breaks `--help` (SP6 shipped one)."""
    from kengash_ai.cli import _command_tree

    broken = [
        c for c in sorted(_command_tree()) if runner.invoke(app, [*c.split(), "--help"]).exit_code
    ]
    assert broken == []
