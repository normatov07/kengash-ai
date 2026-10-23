"""The fake provider CLIs replay queued fixtures, record calls and answer status checks."""

import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import FakeClis


def test_the_fake_replays_records_and_edits(
    fake_clis: FakeClis, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    fake_clis.queue("claude", fixture="claude/review_new.json", edits={"src/a.py": "x = 2\n"})
    result = subprocess.run(["claude", "-p", "hi"], cwd=tmp_path, capture_output=True, text=True)
    assert (result.returncode, result.stdout) == (0, fake_clis.fixture("claude/review_new.json"))
    assert (tmp_path / "src" / "a.py").read_text() == "x = 2\n"
    [call] = fake_clis.calls("claude")
    assert call["argv"] == ["-p", "hi"] and Path(call["cwd"]).resolve() == tmp_path.resolve()
    assert call["env"]["OPENAI_API_KEY"] == "sk-test"


def test_status_commands_answer_without_a_queue(fake_clis: FakeClis) -> None:
    assert subprocess.run(["codex", "login", "status"], capture_output=True).returncode == 0
    fake_clis.sign_out("codex")
    assert subprocess.run(["codex", "login", "status"], capture_output=True).returncode == 1
    unqueued = subprocess.run(["agy", "-p", "x"], capture_output=True, text=True)
    assert (unqueued.returncode, unqueued.stderr) == (97, "fake agy: no reply queued\n")


def test_hidden_clis_are_off_the_path(fake_clis: FakeClis) -> None:
    assert shutil.which("agy") is not None
    fake_clis.hide("agy")
    assert shutil.which("agy") is None
