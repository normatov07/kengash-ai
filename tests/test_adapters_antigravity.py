"""Antigravity adapter: plan mode, stale and denied turns, running usage totals (SP3 spec §8.1)."""

import json
from pathlib import Path
from typing import Any

from conftest import FakeClis

from super_harness.adapters.antigravity import READ_ONLY_LINE, Antigravity
from super_harness.model import OUTPUT_SCHEMAS, ReviewOutput, StepRequest, Usage, WorkOutput


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


def test_detect(fake_clis: FakeClis) -> None:
    assert (Antigravity().detect().version, Antigravity().detect().signed_in) == ("1.4.5", True)
    fake_clis.sign_out("agy")
    assert Antigravity().detect().hint == "run `agy` and sign in"
    assert Antigravity().attach_command("c-1") == ["agy", "--conversation", "c-1"]
