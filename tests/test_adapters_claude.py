"""Claude adapter: command lines, recorded output, error kinds, detection (SP3 spec §8.1)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import FakeClis

from super_harness.adapters.claude import READ_TOOLS, Claude
from super_harness.model import OUTPUT_SCHEMAS, ReviewOutput, StepRequest, Usage, WorkOutput


def _request(tmp_path: Path, **fields: Any) -> StepRequest:
    base = {
        "role": "code-reviewer",
        "cwd": tmp_path,
        "prompt": "",
        "output": "review",
        "profile": "read_only",
        "timeout_s": 5,
        "log": tmp_path / "logs" / "t-1.out",
    }
    return StepRequest.model_validate(base | fields)


def test_new_read_only_session_flags(tmp_path: Path) -> None:
    argv = Claude().command(
        _request(
            tmp_path, prompt="Review", session_id="s-1", model="haiku", skill="---\nname: review"
        )
    )
    assert argv[:3] == ["claude", "-p", "Review"]
    assert argv[argv.index("--session-id") + 1] == "s-1"
    assert argv[argv.index("--append-system-prompt") + 1] == "\n---\nname: review"
    assert json.loads(argv[argv.index("--json-schema") + 1]) == OUTPUT_SCHEMAS["review"]
    assert argv[-10:] == ["--permission-mode", "dontAsk", "--allowedTools", *READ_TOOLS]
    assert {"--setting-sources", "--strict-mcp-config", "--model"} <= set(argv)


def test_resumed_edit_session_flags(tmp_path: Path) -> None:
    argv = Claude().command(
        _request(
            tmp_path,
            prompt="-fix it",
            output="work",
            resume=True,
            session_id="s-1",
            profile="edit_worktree",
            test_cmd="uv run pytest -q",
            lint_cmd="",
        )
    )
    assert argv[:3] == ["claude", "-p", "\n-fix it"]
    assert argv[argv.index("--resume") + 1] == "s-1" and "--session-id" not in argv
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
    assert argv[argv.index("--permission-prompts") + 1] == "none"
    assert argv[-1] == "Bash(uv run pytest -q:*)"


def test_user_config_and_bypass(tmp_path: Path) -> None:
    argv = Claude().command(_request(tmp_path, prompt="p", user_config=True, bypass=True))
    assert "--setting-sources" not in argv and "--permission-mode" not in argv
    assert argv[-1] == "--dangerously-skip-permissions"


def test_commands_never_use_forbidden_flags(tmp_path: Path) -> None:
    for profile in ("read_only", "edit_worktree"):
        argv = Claude().command(_request(tmp_path, prompt="p", profile=profile))
        assert not {"--bare", "--no-session-persistence"} & set(argv)


def test_a_recorded_review_parses(fake_clis: FakeClis, tmp_path: Path) -> None:
    raw = fake_clis.fixture_json("claude/review_new.json")
    fake_clis.queue("claude", fixture="claude/review_new.json")
    result = Claude().run(_request(tmp_path, prompt="Review", session_id=raw["session_id"]))
    assert result.ok and result.session_id == raw["session_id"]
    assert isinstance(result.output, ReviewOutput) and result.output.verdict == "fail"
    assert result.usage == Usage(
        input=raw["usage"]["input_tokens"],
        output=raw["usage"]["output_tokens"],
        cache_read=raw["usage"]["cache_read_input_tokens"],
        cache_write=raw["usage"]["cache_creation_input_tokens"],
        cost_usd=raw["total_cost_usd"],
    )
    [call] = fake_clis.calls("claude")
    assert Path(call["cwd"]).resolve() == tmp_path.resolve()
    assert (tmp_path / "logs" / "t-1.out").read_text() == fake_clis.fixture(
        "claude/review_new.json"
    )


def test_a_recorded_resume_parses_work(fake_clis: FakeClis, tmp_path: Path) -> None:
    raw = fake_clis.fixture_json("claude/work_resume.json")
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    result = Claude().run(
        _request(
            tmp_path,
            prompt="Loop 2",
            output="work",
            resume=True,
            session_id=raw["session_id"],
            profile="edit_worktree",
        )
    )
    assert isinstance(result.output, WorkOutput) and result.session_id == raw["session_id"]


def test_error_kinds(fake_clis: FakeClis, tmp_path: Path) -> None:
    fake_clis.queue("claude", fixture="claude/auth_error.json")
    assert Claude().run(_request(tmp_path, prompt="p")).error == "auth"
    fake_clis.queue("claude", fixture="claude/usage_limit.json")
    limited = Claude().run(_request(tmp_path, prompt="p"))
    assert limited.error == "rate_limit"
    assert limited.retry_after == datetime.fromtimestamp(1793001600, UTC)
    fake_clis.queue("claude", stdout="")
    assert Claude().run(_request(tmp_path, prompt="p")).error == "empty"
    raw = fake_clis.fixture_json("claude/review_new.json")
    raw["structured_output"] = {"verdict": "fail", "summary": "s", "findings": []}
    fake_clis.queue("claude", stdout=json.dumps(raw))
    assert Claude().run(_request(tmp_path, prompt="p")).error == "schema"
    fake_clis.queue("claude", stdout="", stderr="boom", exit=1)
    crashed = Claude().run(_request(tmp_path, prompt="p"))
    assert (crashed.error, crashed.detail) == ("crash", "boom")


def test_timeouts_keep_the_session(fake_clis: FakeClis, tmp_path: Path) -> None:
    fake_clis.queue("claude", fixture="claude/review_new.json", sleep=5)
    result = Claude().run(_request(tmp_path, prompt="p", session_id="s-1", timeout_s=1))
    assert (result.error, result.session_id) == ("timeout", "s-1")


def test_environment_is_scrubbed(
    fake_clis: FakeClis, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("CLAUDECODE", "1")
    fake_clis.queue("claude", fixture="claude/review_new.json")
    Claude().run(_request(tmp_path, prompt="p"))
    [call] = fake_clis.calls("claude")
    assert call["env"] == {"HARNESS_AGENT": "code-reviewer"}


def test_oversized_prompts_fail_before_the_cli_starts(fake_clis: FakeClis, tmp_path: Path) -> None:
    result = Claude().run(_request(tmp_path, prompt="x" * 200_000))
    assert (result.error, result.detail) == ("crash", "prompt is 195 KiB; the limit is 120 KiB")
    assert fake_clis.calls("claude") == []


def test_detect_and_attach(fake_clis: FakeClis) -> None:
    status = Claude().detect()
    assert (status.installed, status.version, status.signed_in, status.auth_method) == (
        True,
        "2.1.309",
        True,
        "claude.ai",
    )
    fake_clis.sign_out("claude")
    assert Claude().detect().hint == "run `claude` and sign in with /login"
    fake_clis.hide("claude")
    assert Claude().detect().installed is False
    assert Claude().attach_command("s-1") == ["claude", "--resume", "s-1"]
