"""Antigravity adapter: plan mode, stale and denied turns, running usage totals (SP3 spec §8.1)."""

import json
from pathlib import Path
from typing import Any

from conftest import FakeClis

from kengash_ai.adapters.antigravity import EDIT_LINE, READ_ONLY_LINE, Antigravity, parse_models
from kengash_ai.model import OUTPUT_SCHEMAS, ReviewOutput, StepRequest, Usage, WorkOutput


def _request(tmp_path: Path, **fields: Any) -> StepRequest:
    base = {
        "role": "doc-writer",
        "cwd": tmp_path,
        "prompt": "",
        "output": "review",
        "profile": "read_only",
        "timeout_s": 5,
        "log": tmp_path / "logs" / "t-1.out",
    }
    return StepRequest.model_validate(base | fields)


def test_read_only_steps_run_in_plan_mode_with_the_read_only_line(tmp_path: Path) -> None:
    argv = Antigravity().command(_request(tmp_path, prompt="Review", skill="---\nrole"))
    assert argv[:3] == ["agy", "-p", f"\n---\nrole\n\nReview\n\n{READ_ONLY_LINE}"]
    assert argv[argv.index("--mode") + 1] == "plan"
    assert "--disable-slash-commands" not in argv


def test_resumed_edits_keep_the_schema(tmp_path: Path) -> None:
    argv = Antigravity().command(
        _request(
            tmp_path,
            prompt="Loop 2",
            output="work",
            resume=True,
            session_id="c-1",
            profile="edit_worktree",
            bypass=True,
        )
    )
    assert argv[argv.index("--conversation") + 1] == "c-1"
    assert json.loads(argv[argv.index("--json-schema") + 1]) == OUTPUT_SCHEMAS["work"]
    assert argv[argv.index("--mode") + 1] == "accept-edits"
    assert argv[-1] == "--dangerously-skip-permissions" and READ_ONLY_LINE not in argv[2]
    assert EDIT_LINE not in argv[2]  # bypass allows terminal commands


def test_editing_steps_say_terminal_commands_are_off(tmp_path: Path) -> None:
    # Live run 2026-10-23: in accept-edits mode headless agy denies its first terminal
    # command and ends the turn with no output.
    argv = Antigravity().command(
        _request(tmp_path, prompt="Implement", output="work", profile="edit_worktree")
    )
    assert argv[2] == f"Implement\n\n{EDIT_LINE}"
    assert argv[argv.index("--mode") + 1] == "accept-edits"


def test_a_recorded_review_parses(fake_clis: FakeClis, tmp_path: Path) -> None:
    raw = fake_clis.fixture_json("agy/review_new.json")
    fake_clis.queue("agy", fixture="agy/review_new.json")
    result = Antigravity().run(_request(tmp_path, prompt="Review"))
    assert result.ok and result.session_id == raw["conversation_id"]
    assert isinstance(result.output, ReviewOutput) and result.output.verdict == "fail"
    usage = raw["usage"]
    assert result.usage == Usage(
        input=usage["input_tokens"],
        output=usage["output_tokens"],
        cache_read=usage["cache_read_tokens"],
    )
    assert result.total_usage == result.usage


def test_resumed_usage_is_the_difference_of_totals(fake_clis: FakeClis, tmp_path: Path) -> None:
    first, second = (
        fake_clis.fixture_json(f"agy/{name}.json") for name in ("review_new", "work_resume")
    )
    fake_clis.queue("agy", fixture="agy/review_new.json")
    prior = Antigravity().run(_request(tmp_path, prompt="Review")).total_usage
    fake_clis.queue("agy", fixture="agy/work_resume.json")
    result = Antigravity().run(
        _request(
            tmp_path,
            prompt="Loop 2",
            output="work",
            resume=True,
            session_id=first["conversation_id"],
            profile="edit_worktree",
            prior_usage=prior,
        )
    )
    assert isinstance(result.output, WorkOutput)
    assert result.usage.output == second["usage"]["output_tokens"] - first["usage"]["output_tokens"]


def test_stale_and_denied_turns(fake_clis: FakeClis, tmp_path: Path) -> None:
    fake_clis.queue("agy", fixture="agy/stale_output.json")
    stale = Antigravity().run(_request(tmp_path, prompt="p", output="work"))
    assert (stale.error, stale.detail) == ("schema", "agy repeated the previous turn's output")
    fake_clis.queue("agy", fixture="agy/denied.json")
    denied = Antigravity().run(_request(tmp_path, prompt="p", output="work"))
    assert (denied.error, denied.detail) == ("empty", "no output; denied: RunCommand")
    fake_clis.queue("agy", fixture="agy/error.json")
    assert Antigravity().run(_request(tmp_path, prompt="p")).error == "auth"


AGY_MODELS = """Fetching available models...
gemini-3.8-flash-high\tGemini 3.8 Flash (High)
gemini-3.8-flash-medium\tGemini 3.8 Flash (Medium)
gemini-3.8-flash-low\tGemini 3.8 Flash (Low)
claude-sonnet-4-6\tClaude Sonnet 4.6 (Thinking)
claude-opus-4-6-thinking\tClaude Opus 4.6 (Thinking)
gpt-oss-120b-medium\tGPT-OSS 120B (Medium)
"""  # agy 1.4.11, 2026-10-30


def test_agy_models_parse() -> None:
    assert parse_models(AGY_MODELS) == [
        "gemini-3.8-flash-high",
        "gemini-3.8-flash-medium",
        "gemini-3.8-flash-low",
        "claude-sonnet-4-6",
        "claude-opus-4-6-thinking",
        "gpt-oss-120b-medium",
    ]
    assert parse_models("gemini-3-pro\n") == ["gemini-3-pro"]
    assert parse_models("Error: not signed in\n") == []


def test_detect(fake_clis: FakeClis) -> None:
    assert (Antigravity().detect().version, Antigravity().detect().signed_in) == ("1.4.5", True)
    assert Antigravity().detect().models == ["gemini-3-pro"]
    fake_clis.sign_out("agy")
    assert Antigravity().detect().hint == "run `agy` and sign in"
    assert Antigravity().detect().models == []
    assert Antigravity().attach_command("c-1") == ["agy", "--conversation", "c-1"]


CONV = "00ece9a5-c212-489d-96a6-e940bb74edc0"
RESET = "read tcp 10.0.0.1:47416->172.217.115.4:443: read: connection reset by peer"


def _stream(*events: dict[str, Any]) -> str:
    return "".join(json.dumps(event) + "\n" for event in events)


def _result(**fields: Any) -> dict[str, Any]:
    return {"event": "result", "result": {"conversation_id": CONV, **fields}}


INIT = {"event": "init", "conversation_id": CONV, "init": {"model": "m"}}


def test_editing_steps_stream(tmp_path: Path) -> None:
    argv = Antigravity().command(_request(tmp_path, prompt="p", output="work"))
    assert argv[argv.index("--output-format") + 1] == "stream-json"


def test_stream_ok_parses_the_result(fake_clis: FakeClis, tmp_path: Path) -> None:
    fake_clis.queue("agy", fixture="agy/stream-ok.jsonl")
    result = Antigravity().run(_request(tmp_path, prompt="p", output="work"))
    assert (result.error, result.session_id) == (None, CONV)
    assert isinstance(result.output, WorkOutput)
    assert result.output.summary == "Rebrand core package and UI to Chess Samurai"


def test_error_with_a_valid_output_is_a_success_with_a_warning(
    fake_clis: FakeClis, tmp_path: Path
) -> None:
    fake_clis.queue("agy", fixture="agy/stream-error-valid.jsonl", exit=1)
    result = Antigravity().run(_request(tmp_path, prompt="p", output="work"))
    assert result.error is None and result.output is not None
    assert result.output.summary == "Rebrand core package and UI to Chess Samurai"
    assert "connection reset by peer" in result.warning


def test_an_invalid_output_with_an_error_stays_an_error(
    fake_clis: FakeClis, tmp_path: Path
) -> None:
    broken = {"summary": 1}
    stdout = _stream(
        INIT,
        _result(status="ERROR", error=RESET, response=json.dumps(broken), structured_output=broken),
    )
    fake_clis.queue("agy", stdout=stdout, exit=1)
    result = Antigravity().run(_request(tmp_path, prompt="p", output="work"))
    assert (result.error, result.session_id) == ("network", CONV)


def test_the_error_field_is_classified_not_the_response(
    fake_clis: FakeClis, tmp_path: Path
) -> None:
    said = "I checked the quota exceeded handler and the 401 page."
    fake_clis.queue(
        "agy", stdout=_stream(INIT, _result(status="ERROR", error=RESET, response=said))
    )
    assert Antigravity().run(_request(tmp_path, prompt="p", output="work")).error == "network"


def test_recover_session_reads_init(tmp_path: Path) -> None:
    log = tmp_path / "t-1.out"
    log.write_text(_stream(INIT, {"event": "step_update", "step_update": {}}), encoding="utf-8")
    assert Antigravity().recover_session(log) == CONV
    log.write_text("not json\n", encoding="utf-8")
    assert Antigravity().recover_session(log) is None


def test_no_result_classifies_stderr(fake_clis: FakeClis, tmp_path: Path) -> None:
    fake_clis.queue("agy", stdout=_stream(INIT), stderr=f"fatal: {RESET}\n", exit=1)
    result = Antigravity().run(_request(tmp_path, prompt="p", output="work"))
    assert (result.error, result.session_id) == ("network", CONV)


def test_edit_steps_allow_reads(tmp_path: Path) -> None:
    argv = Antigravity().command(
        _request(tmp_path, prompt="p", output="work", profile="edit_worktree")
    )
    allow = json.loads(argv[argv.index("--settings") + 1])
    assert allow == {"permissions": {"allow": ["read_file(*)"]}}
    read_only = Antigravity().command(_request(tmp_path, prompt="p"))
    assert "--settings" not in read_only
