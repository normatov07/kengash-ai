"""Codex adapter: command lines, JSONL events, error kinds, session recovery (SP3 spec §8.1)."""

import json
from pathlib import Path
from typing import Any

from conftest import FakeClis

from kengash_ai.adapters.codex import Codex
from kengash_ai.model import OUTPUT_SCHEMAS, ReviewOutput, StepRequest, Usage


def _request(tmp_path: Path, **fields: Any) -> StepRequest:
    base = {
        "role": "plan-reviewer",
        "cwd": tmp_path,
        "prompt": "",
        "output": "review",
        "profile": "read_only",
        "timeout_s": 5,
        "log": tmp_path / "logs" / "t-1.out",
    }
    return StepRequest.model_validate(base | fields)


def test_new_session_flags(tmp_path: Path) -> None:
    codex = Codex(tmp_path / "schemas")
    argv = codex.command(_request(tmp_path, prompt="Review", skill="Be terse.", model="gpt-5"))
    assert argv[:5] == [
        "codex",
        "exec",
        "--json",
        "--output-schema",
        str(tmp_path / "schemas" / "review.json"),
    ]
    assert argv[argv.index("-s") + 1] == "read-only" and argv[argv.index("-m") + 1] == "gpt-5"
    assert "--ignore-user-config" in argv and argv[-1] == "Be terse.\n\nReview"
    assert (
        json.loads((tmp_path / "schemas" / "review.json").read_text()) == OUTPUT_SCHEMAS["review"]
    )


def test_resume_takes_the_sandbox_as_config(tmp_path: Path) -> None:
    argv = Codex(tmp_path).command(
        _request(
            tmp_path,
            prompt="Loop 2",
            output="work",
            resume=True,
            session_id="t-1",
            profile="edit_worktree",
        )
    )
    assert argv[:3] == ["codex", "exec", "resume"]
    assert argv[argv.index("-c") + 1] == 'sandbox_mode="workspace-write"'
    assert "-s" not in argv and "-C" not in argv and argv[-2:] == ["t-1", "Loop 2"]


def test_bypass_replaces_the_sandbox_and_no_ephemeral(tmp_path: Path) -> None:
    argv = Codex(tmp_path).command(_request(tmp_path, prompt="p", bypass=True, user_config=True))
    assert "--dangerously-bypass-approvals-and-sandbox" in argv
    assert not {"-s", "--ignore-user-config", "--ephemeral"} & set(argv)


def test_a_review_parses(fake_clis: FakeClis, tmp_path: Path) -> None:
    fake_clis.queue("codex", fixture="codex/review_new.jsonl")
    result = Codex(tmp_path).run(_request(tmp_path, prompt="Review"))
    assert result.ok and result.session_id == "0199a213-81c0-7800-8aa1-bbab2a035a53"
    assert result.output == ReviewOutput(verdict="pass", summary="No issues found.", findings=[])
    assert result.usage == Usage(input=315, output=122, cache_read=24448)


def test_usage_limits_and_missing_output(fake_clis: FakeClis, tmp_path: Path) -> None:
    fake_clis.queue("codex", fixture="codex/usage_limit.jsonl")
    assert Codex(tmp_path).run(_request(tmp_path, prompt="p")).error == "rate_limit"
    fake_clis.queue("codex", stdout='{"type":"thread.started","thread_id":"t"}\n')
    assert Codex(tmp_path).run(_request(tmp_path, prompt="p")).error == "empty"
    fake_clis.queue("codex", stdout="", stderr="Not logged in", exit=1)
    assert Codex(tmp_path).run(_request(tmp_path, prompt="p")).error == "auth"


def test_a_killed_step_recovers_its_thread(tmp_path: Path, fake_clis: FakeClis) -> None:
    log = tmp_path / "k-1.out"
    log.write_text(fake_clis.fixture("codex/review_new.jsonl").splitlines()[0] + "\n")
    assert Codex(tmp_path).recover_session(log) == "0199a213-81c0-7800-8aa1-bbab2a035a53"
    assert Codex(tmp_path).recover_session(tmp_path / "none.out") is None


def test_detect(fake_clis: FakeClis, tmp_path: Path) -> None:
    assert Codex(tmp_path).detect().version == "0.161.0"
    fake_clis.sign_out("codex")
    assert Codex(tmp_path).detect().hint == "run `codex login`"
    assert Codex(tmp_path).attach_command("t-1") == ["codex", "resume", "t-1"]


def test_an_error_event_followed_by_a_completed_turn_is_not_a_failure(
    fake_clis: FakeClis, tmp_path: Path
) -> None:
    lines = fake_clis.fixture("codex/review_new.jsonl").splitlines()
    retry = json.dumps({"type": "error", "message": "stream disconnected; retrying 1/5"})
    fake_clis.queue("codex", stdout="\n".join([lines[0], lines[1], retry, *lines[2:]]) + "\n")
    result = Codex(tmp_path).run(_request(tmp_path, prompt="Review"))
    assert result.ok and isinstance(result.output, ReviewOutput)
