"""The plugin manifests pass each agent's own validator (SP4 spec decision 10); no model
calls, but they need the real CLIs, so they run with `-m live`."""

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.live
ROOT = Path(__file__).resolve().parents[2]
VALIDATORS = {"claude": shutil.which("claude"), "agy": shutil.which("agy")}


@pytest.fixture
def fake_clis() -> None:
    """Replaces the autouse fakes: the validators are the real CLIs."""


@pytest.mark.parametrize("cli", sorted(VALIDATORS))
def test_the_plugin_validates(cli: str) -> None:
    binary = VALIDATORS[cli]
    if binary is None:
        pytest.skip(f"{cli} is not installed")
    result = subprocess.run(
        [binary, "plugin", "validate", str(ROOT)], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stdout + result.stderr
