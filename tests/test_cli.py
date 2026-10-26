import re
import shutil
import subprocess

import pytest
from typer.testing import CliRunner

from super_harness import __version__
from super_harness.cli import app

runner = CliRunner()


def test_version_names_the_package() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"super-harness {__version__}"


def test_help_lists_the_version_option() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    # Typer forces Rich colours under GITHUB_ACTIONS, so CI help text carries escape codes
    assert "--version" in re.sub(r"\x1b\[[0-9;]*m", "", result.output)


@pytest.mark.parametrize("command", ["harness", "hrn"])
def test_console_scripts_print_version(command: str) -> None:
    executable = shutil.which(command)
    assert executable, f"{command} is not on PATH; run `make setup`"
    output = subprocess.run(
        [executable, "--version"], check=True, capture_output=True, text=True
    ).stdout
    assert output.strip() == f"super-harness {__version__}"
