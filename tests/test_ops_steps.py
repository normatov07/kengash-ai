"""The step loop: one ticket through its workflow with fake CLIs (SP3 spec §5)."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import Engine, Events, FakeClis, write_settings

from kengash_ai.model import Running, TicketState
from kengash_ai.ops import calls, steps
from kengash_ai.ops.steps import JobEnd
from kengash_ai.store import StorePaths, documents, runtime
from kengash_ai.workflow import fingerprint

REVIEW_FAIL = {
    "verdict": "fail",
    "summary": "Missing jitter.",
    "findings": [
        {
            "severity": "medium",
            "file": "retry.py",
            "line": 3,
            "issue": "no jitter",
            "fix": "add jitter",
        }
    ],
}
REVIEW_PASS = {"verdict": "pass", "summary": "Good.", "findings": []}


def test_one_step_writes_handoff_log_tokens_and_session(
    engine: Engine, fake_clis: FakeClis, journal_events: Events
) -> None:
    raw = fake_clis.fixture_json("claude/work_resume.json")
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    end = steps.run_job("7b55e0c1", steps=1)
    assert end == JobEnd("in_process/paused", "step budget spent")
    doc = engine.ticket()
    assert (
        doc.meta.step == "implement"
        and doc.meta.tokens == raw["usage"]["input_tokens"] + raw["usage"]["output_tokens"]
    )
    assert doc.sections["Handoff"] == raw["structured_output"]["handoff"]
    assert (
        doc.sections["Log"]
        .splitlines()[-1]
        .endswith(f"· plan · planner · claude/opus · pass · {doc.meta.tokens}")
    )
    assert doc.meta.sessions["planner"].id == raw["session_id"]
    [call] = fake_clis.calls("claude")
    assert (
        "--session-id" in call["argv"] and Path(call["cwd"]).resolve() == engine.worktree.resolve()
    )
    types = [e["type"] for e in journal_events()]
    assert types[-4:] == ["step.start", "session.created", "step.end", "ticket.paused"]


def test_a_full_simple_workflow(
    engine: Engine, fake_clis: FakeClis, run_git: Callable[..., str]
) -> None:
    fake_clis.queue("claude", fixture="claude/work_resume.json")  # plan
    fake_clis.queue(
        "codex", fixture="codex/work_resume.jsonl", edits={"retry.py": "retries = 3\n"}
    )  # implement
    fake_clis.queue("claude", stdout=fake_clis.claude_output(REVIEW_FAIL))  # review fails
    fake_clis.queue(
        "codex",
        fixture="codex/work_resume.jsonl",
        edits={"retry.py": "retries = 3\njitter = True\n"},
    )
    fake_clis.queue("claude", stdout=fake_clis.claude_output(REVIEW_PASS))  # review passes
    end = steps.run_job("7b55e0c1")
    assert end == JobEnd("in_process/awaiting_merge", "every step passed")
    doc = engine.ticket()
    assert (doc.meta.loop, doc.meta.step, doc.sections["Findings"]) == (2, None, "")
    log = run_git(engine.worktree, "log", "--format=%s%n%(trailers:only,unfold)", "main..HEAD")
    assert "hrn(7b55e0c1): loop 2 implement: Added retry with backoff." in log
    assert f"Harness-Ticket: {doc.meta.uuid}" in log and "Harness-Model: codex/default" in log
    reviews = [c["argv"] for c in fake_clis.calls("claude")][1:]
    assert (
        "--session-id" in reviews[0]
        and reviews[1][reviews[1].index("--resume") + 1] == doc.meta.sessions["code-reviewer"].id
    )
    assert fake_clis.calls("codex")[1]["argv"][:2] == ["exec", "resume"]


def test_a_failing_review_writes_findings_and_recirculates(
    engine: Engine, fake_clis: FakeClis
) -> None:
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"retry.py": "retries = 3\n"})
    fake_clis.queue("claude", stdout=fake_clis.claude_output(REVIEW_FAIL))
    steps.run_job("7b55e0c1", steps=3)
    doc = engine.ticket()
    assert (doc.meta.loop, doc.meta.step) == (2, "implement")
    assert doc.sections["Findings"] == "- medium · retry.py:3 · no jitter · add jitter"
    assert engine.state().streaks == {"review_code": {fingerprint("retry.py", "no jitter"): 1}}


def test_an_agent_commit_is_folded_into_the_harness_commit(
    engine: Engine, fake_clis: FakeClis, run_git: Callable[..., str]
) -> None:
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue(
        "codex",
        fixture="codex/work_resume.jsonl",
        edits={"retry.py": "retries = 3\n"},
        shell="git add -A && git commit -qm 'agent commit'",
    )
    steps.run_job("7b55e0c1", steps=2)
    subjects = run_git(engine.worktree, "log", "--format=%s", "main..HEAD").splitlines()
    assert subjects == ["hrn(7b55e0c1): loop 1 implement: Added retry with backoff."]


def test_a_timeout_retries_once_then_fails(
    engine: Engine, fake_clis: FakeClis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(calls, "step_timeout", lambda resolved: 1)
    fake_clis.queue("claude", fixture="claude/work_resume.json", sleep=3)
    fake_clis.queue("claude", fixture="claude/work_resume.json", sleep=3)
    end = steps.run_job("7b55e0c1")
    assert end.status == "in_process/failed" and end.reason.startswith(
        "timeout: killed after 1 s twice; log: "
    )
    assert len(fake_clis.calls("claude")) == 2


def test_schema_errors_get_one_repair_turn(engine: Engine, fake_clis: FakeClis) -> None:
    bad = fake_clis.claude_output({"summary": "s"})  # handoff missing
    fake_clis.queue("claude", stdout=bad)
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    steps.run_job("7b55e0c1", steps=1)
    second = fake_clis.calls("claude")[1]["argv"]
    assert "--resume" in second and second[1].startswith(
        "Your last reply failed: output does not match the work schema"
    )
    assert engine.ticket().meta.step == "implement"


def test_rate_limits_fall_back_then_wait(
    engine: Engine, fake_clis: FakeClis, monkeypatch: pytest.MonkeyPatch
) -> None:
    naps: list[float] = []
    monkeypatch.setattr(steps, "sleep", naps.append)
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue("codex", fixture="codex/usage_limit.jsonl")  # implementer on codex
    fake_clis.queue("claude", fixture="claude/work_resume.json")  # fallback claude/sonnet
    steps.run_job("7b55e0c1", steps=2)
    fallback = fake_clis.calls("claude")[1]["argv"]
    assert fallback[fallback.index("--model") + 1] == "sonnet" and naps == []
    assert engine.ticket().meta.sessions["implementer"].provider == "claude"


QUOTA_RESET = datetime(2026, 10, 26, 8, 0, tzinfo=UTC)  # the reset claude/usage_limit.json names


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (QUOTA_RESET - timedelta(seconds=90), [60.0, 30.0]),  # sleeps until the reset, in naps
        (QUOTA_RESET + timedelta(hours=1), []),  # a reset already past: retry at once
    ],
)
def test_quota_waits_without_a_fallback(
    engine: Engine,
    fake_clis: FakeClis,
    store_paths: StorePaths,
    monkeypatch: pytest.MonkeyPatch,
    now: datetime,
    expected: list[float],
) -> None:
    naps: list[float] = []
    monkeypatch.setattr(steps, "sleep", naps.append)
    monkeypatch.setattr(steps, "utc_now", lambda: now)  # the fixture's reset time is fixed
    write_settings(store_paths, "fallback_on_rate_limit: false\n")
    fake_clis.queue("claude", fixture="claude/usage_limit.json")
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    steps.run_job("7b55e0c1", steps=1)
    assert naps == expected and engine.ticket().meta.step == "implement"


def test_auth_and_crash_fail_the_ticket(engine: Engine, fake_clis: FakeClis) -> None:
    fake_clis.queue("claude", fixture="claude/auth_error.json")
    assert steps.run_job("7b55e0c1") == JobEnd(
        "in_process/failed", "sign in to claude interactively"
    )


def test_a_failing_hook_gets_one_repair_turn(engine: Engine, fake_clis: FakeClis) -> None:
    hook = engine.repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\ntest -f fixed || { echo 'lint: add fixed'; exit 1; }\n")
    hook.chmod(0o755)
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"retry.py": "x = 1\n"})
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"fixed": "yes\n"})
    steps.run_job("7b55e0c1", steps=2)
    repair = fake_clis.calls("codex")[1]["argv"]
    assert "lint: add fixed" in repair[-1] and engine.ticket().meta.step == "review_code"


def test_a_ticket_moved_during_its_step_keeps_the_users_status(
    engine: Engine, fake_clis: FakeClis
) -> None:
    move = "harness ticket move 7b55e0c1 done --why 'user closed it' --by user"
    fake_clis.queue("claude", fixture="claude/work_resume.json", shell=move)
    end = steps.run_job("7b55e0c1")
    assert end == JobEnd("done/closed", "changed while the step ran")
    assert (
        engine.ticket().meta.status == "done/closed" and runtime.load_slots(engine.paths).held == []
    )


def test_park_and_pause_flags_stop_before_the_next_step(
    engine: Engine, fake_clis: FakeClis
) -> None:
    runtime.set_park(engine.paths, "7b55e0c1", on=True)
    assert steps.run_job("7b55e0c1").status == "in_queue/parked"
    assert engine.ticket().meta.step == "plan" and not runtime.park_requested(
        engine.paths, "7b55e0c1"
    )


def test_a_dead_workers_codex_session_is_recovered(engine: Engine, fake_clis: FakeClis) -> None:
    log = engine.paths.logs / "7b55e0c1-1.out"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(fake_clis.fixture("codex/review_new.jsonl").splitlines()[0] + "\n")
    doc = engine.ticket()
    doc.meta.step, doc.meta.status = "implement", "in_process/under_implementation"
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    running = Running(role="implementer", provider="codex", log=log)
    runtime.save_ticket_state(engine.paths, "7b55e0c1", TicketState(running=running, calls=1))
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"retry.py": "x = 1\n"})
    steps.run_job("7b55e0c1", steps=1)
    argv = fake_clis.calls("codex")[0]["argv"]
    assert argv[:2] == ["exec", "resume"] and "0199a213-81c0-7800-8aa1-bbab2a035a53" in argv


def test_auto_merge_ends_the_job_merged(
    engine: Engine, fake_clis: FakeClis, store_paths: StorePaths
) -> None:
    write_settings(store_paths, "merge.mode: auto\n")
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"retry.py": "retries = 3\n"})
    fake_clis.queue("claude", stdout=fake_clis.claude_output(REVIEW_PASS))
    end = steps.run_job("7b55e0c1")
    assert end.status == "done/merged"
    assert (engine.repo / "retry.py").exists() and not engine.worktree.exists()


def test_a_new_claude_session_that_never_started_is_forgotten(
    engine: Engine, fake_clis: FakeClis
) -> None:
    fake_clis.queue("claude", stdout="", stderr="boom", exit=1)
    assert steps.run_job("7b55e0c1").status == "in_process/failed"
    assert "planner" not in engine.ticket().meta.sessions


def test_a_timed_out_new_claude_session_retries_by_resuming(
    engine: Engine, fake_clis: FakeClis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(calls, "step_timeout", lambda resolved: 1)
    fake_clis.queue("claude", fixture="claude/work_resume.json", sleep=3)
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    steps.run_job("7b55e0c1", steps=1)
    first, second = (call["argv"] for call in fake_clis.calls("claude"))
    session = first[first.index("--session-id") + 1]
    assert "--session-id" not in second and second[second.index("--resume") + 1] == session
    assert engine.ticket().meta.step == "implement"


def test_a_denied_command_gets_one_repair_turn(engine: Engine, fake_clis: FakeClis) -> None:
    write_settings(
        engine.paths, "agents:\n  planner: {cli: antigravity, skill: plan, fallback: []}\n"
    )
    fake_clis.queue("agy", fixture="agy/denied.json")
    fake_clis.queue("agy", fixture="agy/work_resume.json")
    steps.run_job("7b55e0c1", steps=1)
    second = fake_clis.calls("agy")[1]["argv"]
    assert "--conversation" in second and "RunCommand" in second[1]
    assert engine.ticket().meta.step == "implement"


CUSTOM = """\
agents:
  helper: {{cli: claude/sonnet, skill: helper}}
steps.{step}: {{role: helper, kind: {kind}, does: Polish the change.}}
workflows:
  simple: {{steps: [plan, implement, {step}], on_fail: {edges}}}
"""


def custom_step(paths: StorePaths, step: str, kind: str, edges: str = "{}") -> None:
    write_settings(paths, CUSTOM.format(step=step, kind=kind, edges=edges))


def test_a_custom_edit_step_is_committed(
    engine: Engine, fake_clis: FakeClis, store_paths: StorePaths, run_git: Callable[..., str]
) -> None:
    custom_step(store_paths, "tidy", "edit")
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"retry.py": "retries = 3\n"})
    fake_clis.queue("claude", fixture="claude/work_resume.json", edits={"notes.md": "tidy\n"})
    end = steps.run_job("7b55e0c1")
    assert end == JobEnd("in_process/awaiting_merge", "every step passed")
    subjects = run_git(engine.worktree, "log", "--format=%s", "main..HEAD").splitlines()
    assert subjects[0].startswith("hrn(7b55e0c1): loop 1 tidy: Renamed")
    tidy = fake_clis.calls("claude")[1]
    assert "Polish the change. Do not commit; harness commits." in " ".join(tidy["argv"])


def test_a_custom_review_step_sends_the_ticket_back(
    engine: Engine, fake_clis: FakeClis, store_paths: StorePaths
) -> None:
    custom_step(store_paths, "perf_review", "review", "{perf_review: implement}")
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"retry.py": "retries = 3\n"})
    fake_clis.queue("claude", stdout=fake_clis.claude_output(REVIEW_FAIL))
    steps.run_job("7b55e0c1", steps=3)
    doc = engine.ticket()
    assert (doc.meta.loop, doc.meta.step) == (2, "implement")
    assert doc.sections["Findings"] == "- medium · retry.py:3 · no jitter · add jitter"
    assert doc.meta.sessions["helper"].id


def test_a_custom_read_step_hands_notes_on(
    engine: Engine, fake_clis: FakeClis, store_paths: StorePaths, run_git: Callable[..., str]
) -> None:
    custom_step(store_paths, "advise", "read")
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"retry.py": "retries = 3\n"})
    raw = fake_clis.fixture_json("claude/work_resume.json")
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    steps.run_job("7b55e0c1")
    assert engine.ticket().sections["Handoff"] == raw["structured_output"]["handoff"]
    subjects = run_git(engine.worktree, "log", "--format=%s", "main..HEAD").splitlines()
    assert [s for s in subjects if " advise:" in s] == []
