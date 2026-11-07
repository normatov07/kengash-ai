"""The step loop: one ticket through its workflow with fake CLIs (SP3 spec §5)."""

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from conftest import Engine, Events, FakeClis, write_settings

from kengash_ai import gitops
from kengash_ai.model import Doc, Running, SentBack, StepRequest, StepResult, Ticket, TicketState
from kengash_ai.ops import calls, prompts, steps
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
    assert "kg(7b55e0c1): loop 2 implement: Added retry with backoff." in log
    assert f"Kengash-Ticket: {doc.meta.uuid}" in log and "Kengash-Model: codex/default" in log
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
    assert subjects == ["kg(7b55e0c1): loop 1 implement: Added retry with backoff."]


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
        "Your last reply failed: output does not match the plan schema"
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
    write_settings(store_paths, "fallback_on_error: false\n")
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
    move = "kengash ticket move 7b55e0c1 done --why 'user closed it' --by user"
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
merge.mode: ask
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
    assert subjects[0].startswith("kg(7b55e0c1): loop 1 tidy: Renamed")
    tidy = fake_clis.calls("claude")[1]
    assert "Polish the change. Do not commit; kengash commits." in " ".join(tidy["argv"])


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


def test_a_custom_step_between_built_ins_runs_in_order(
    engine: Engine, fake_clis: FakeClis, store_paths: StorePaths
) -> None:
    text = CUSTOM.replace("[plan, implement, {step}]", "[plan, {step}, implement]")
    write_settings(store_paths, text.format(step="advise", kind="read", edges="{}"))
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"retry.py": "retries = 3\n"})
    end = steps.run_job("7b55e0c1")
    assert end == JobEnd("in_process/awaiting_merge", "every step passed")
    planner, advisor = (" ".join(call["argv"]) for call in fake_clis.calls("claude"))
    assert (
        "Polish the change." not in planner and "Polish the change. Do not edit files." in advisor
    )
    assert len(fake_clis.calls("codex")) == 1


def _codex_cut(thread: str | None = "th-1") -> str:
    """A codex turn that a connection reset ended; `thread` None: before the session began."""
    events: list[dict[str, object]] = (
        [{"type": "thread.started", "thread_id": thread}] if thread else []
    )
    events.append(
        {"type": "turn.failed", "error": {"message": "stream error: connection reset by peer"}}
    )
    return "".join(json.dumps(event) + "\n" for event in events)


def test_network_error_resumes_once_then_passes(engine: Engine, fake_clis: FakeClis) -> None:
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue("codex", stdout=_codex_cut(), exit=1)
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"x.py": "x = 1\n"})
    steps.run_job("7b55e0c1", steps=2)
    resumed = fake_clis.calls("codex")[1]["argv"]
    assert "resume" in resumed and "th-1" in resumed and resumed[-1] == prompts.NETWORK_PROMPT
    assert engine.ticket().meta.step == "review_code"


def test_network_error_without_a_session_retries_fresh(engine: Engine, fake_clis: FakeClis) -> None:
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue("codex", stdout=_codex_cut(None), exit=1)
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"x.py": "x = 1\n"})
    steps.run_job("7b55e0c1", steps=2)
    assert "resume" not in fake_clis.calls("codex")[1]["argv"]
    assert engine.ticket().meta.step == "review_code"


def test_network_then_fallback_then_failure(engine: Engine, fake_clis: FakeClis) -> None:
    cut = json.dumps(
        {"type": "result", "is_error": True, "session_id": "c-9", "result": "API Error: ECONNRESET"}
    )
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue("codex", stdout=_codex_cut(), exit=1)
    fake_clis.queue("codex", stdout=_codex_cut(), exit=1)
    fake_clis.queue("claude", stdout=cut + "\n", exit=1)  # the fallback, claude/sonnet
    fake_clis.queue("claude", stdout=cut + "\n", exit=1)
    end = steps.run_job("7b55e0c1", steps=2)
    assert end.status == "in_process/failed" and end.reason.startswith("network: ")
    assert len(fake_clis.calls("codex")) == 2 and len(fake_clis.calls("claude")) == 3


def test_auth_is_never_retried(engine: Engine, fake_clis: FakeClis) -> None:
    fake_clis.queue("claude", fixture="claude/auth_error.json")
    steps.run_job("7b55e0c1")
    assert len(fake_clis.calls("claude")) == 1


def test_a_failed_call_keeps_its_session(engine: Engine, fake_clis: FakeClis) -> None:
    failed = [
        {"type": "thread.started", "thread_id": "th-9"},
        {"type": "turn.failed", "error": {"message": "the model gave up"}},
    ]
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue("codex", stdout="".join(json.dumps(e) + "\n" for e in failed), exit=1)
    end = steps.run_job("7b55e0c1", steps=2)
    assert end.status == "in_process/failed"
    session = engine.ticket().meta.sessions["implementer"]
    assert (session.provider, session.id) == ("codex", "th-9")


def test_commit_hook_turn_survives_a_network_error(engine: Engine, fake_clis: FakeClis) -> None:
    hook = engine.repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\ntest -f fixed || { echo 'lint: add fixed'; exit 1; }\n")
    hook.chmod(0o755)
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"retry.py": "x = 1\n"})
    fake_clis.queue("codex", stdout=_codex_cut(), exit=1)
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"fixed": "yes\n"})
    steps.run_job("7b55e0c1", steps=2)
    assert fake_clis.calls("codex")[2]["argv"][-1] == prompts.NETWORK_PROMPT
    assert engine.ticket().meta.step == "review_code"


def test_running_log_follows_each_attempt_and_clears(engine: Engine, fake_clis: FakeClis) -> None:
    seen: list[str] = []
    real = steps._next_log

    def spy(job: steps._Job) -> Path:
        path = real(job)
        running = runtime.load_ticket_state(engine.paths, engine.ticket_id).running
        seen.append(running.log.name if running else "")
        return path

    steps._next_log = spy
    try:
        fake_clis.queue("claude", fixture="claude/work_resume.json")
        fake_clis.queue("codex", stdout=_codex_cut(), exit=1)
        fake_clis.queue("codex", stdout=_codex_cut(), exit=1)
        fake_clis.queue("claude", fixture="claude/auth_error.json")
        steps.run_job("7b55e0c1", steps=2)
    finally:
        steps._next_log = real
    assert seen[-1] == f"{engine.ticket_id}-{len(seen)}.out"
    assert runtime.load_ticket_state(engine.paths, engine.ticket_id).running is None


def test_a_failure_on_an_editing_step_names_the_worktree(
    engine: Engine, fake_clis: FakeClis
) -> None:
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    failed = [
        {"type": "thread.started", "thread_id": "th-9"},
        {"type": "turn.failed", "error": {"message": "gave up"}},
    ]
    fake_clis.queue(
        "codex",
        stdout="".join(json.dumps(e) + "\n" for e in failed),
        exit=1,
        edits={"x.py": "x = 1\n"},
    )
    end = steps.run_job("7b55e0c1", steps=2)
    assert end.reason.endswith(f"; work kept in {engine.worktree} (1 files changed)")


def test_a_retry_over_changes_gets_the_note(engine: Engine, fake_clis: FakeClis) -> None:
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    failed = {"type": "turn.failed", "error": {"message": "gave up"}}
    fake_clis.queue("codex", stdout=json.dumps(failed) + "\n", exit=1, edits={"x.py": "x = 1\n"})
    steps.run_job("7b55e0c1", steps=2)
    doc = engine.ticket()
    doc.meta.status = "in_process/under_implementation"  # what `kengash run` does on a retry
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl")
    steps.run_job("7b55e0c1", steps=1)
    assert prompts.RETRY_NOTE in fake_clis.calls("codex")[1]["argv"][-1]


def test_a_new_claude_session_cut_before_it_began_retries_fresh(
    engine: Engine, fake_clis: FakeClis
) -> None:
    fake_clis.queue("claude", stderr="connect ECONNREFUSED 160.79.104.10:443\n", exit=1)
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    steps.run_job("7b55e0c1", steps=1)
    first, second = (call["argv"] for call in fake_clis.calls("claude")[:2])
    assert "--resume" not in second
    assert second[second.index("--session-id") + 1] == first[first.index("--session-id") + 1]
    assert engine.ticket().meta.step == "implement"


def test_a_late_warning_is_journaled_and_logged(
    engine: Engine, fake_clis: FakeClis, journal_events: Events
) -> None:
    late = json.loads(fake_clis.fixture("claude/work_resume.json"))
    late["is_error"], late["result"] = True, "API Error: Connection error. (ECONNRESET)"
    fake_clis.queue("claude", stdout=json.dumps(late), exit=1)
    steps.run_job("7b55e0c1", steps=1)
    (end,) = [e for e in journal_events() if e["type"] == "step.end"]
    assert "ECONNRESET" in end["warning"]
    assert "warning: API Error: Connection error. (ECONNRESET)" in engine.ticket().sections["Log"]


def _hook(engine: Engine) -> None:
    hook = engine.repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\ntest -f fixed || { echo 'lint: add fixed'; exit 1; }\n")
    hook.chmod(0o755)


def test_a_hook_that_fails_twice_names_the_worktree_and_keeps_the_session(
    engine: Engine, fake_clis: FakeClis
) -> None:
    _hook(engine)
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"retry.py": "x = 1\n"})
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl")  # the repair fixes nothing
    end = steps.run_job("7b55e0c1", steps=2)
    assert end.reason.startswith("commit failed: lint: add fixed")
    assert end.reason.endswith(f"; work kept in {engine.worktree} (1 files changed)")
    session = engine.ticket().meta.sessions["implementer"]
    assert session.provider == "codex" and session.id


def test_a_failed_hook_repair_names_the_worktree_and_keeps_the_session(
    engine: Engine, fake_clis: FakeClis
) -> None:
    _hook(engine)
    failed = [
        {"type": "thread.started", "thread_id": "th-9"},
        {"type": "turn.failed", "error": {"message": "the model gave up"}},
    ]
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"retry.py": "x = 1\n"})
    fake_clis.queue("codex", stdout="".join(json.dumps(e) + "\n" for e in failed), exit=1)
    end = steps.run_job("7b55e0c1", steps=2)
    assert end.reason.endswith(f"; work kept in {engine.worktree} (1 files changed)")
    assert engine.ticket().meta.sessions["implementer"].id == "th-9"


def checks_settings(test_cmd: str, *, turns: int | None = None, run_tests: bool = True) -> str:
    """Settings with `test_cmd`, the shell test-runner on, and run_tests after implement."""
    if run_tests:
        flow = "[plan, implement, run_tests, review_code], on_fail: {run_tests: implement, "
    else:
        flow = "[plan, implement, review_code], on_fail: {"
    text = (
        f"project.test_cmd: {json.dumps(test_cmd)}\n"
        "agents:\n  test-runner: {on: true, cli: shell, skill: run-tests}\n"
        f"workflows:\n  simple: {{steps: {flow}review_code: implement}}}}\n"
    )
    return text + (f"checks.turns: {turns}\n" if turns is not None else "")


BOOM = "echo 'error: boom' && exit 1"
BOOM_HEADLINE = f"`{BOOM}` exit 1: error: boom"


def test_a_failing_check_writes_check_output_and_sends_it_back(
    engine: Engine, fake_clis: FakeClis
) -> None:
    write_settings(engine.paths, checks_settings(BOOM, turns=0))
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"retry.py": "retries = 3\n"})
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"retry.py": "retries = 4\n"})
    steps.run_job("7b55e0c1", steps=3)
    doc = engine.ticket()
    assert (doc.meta.step, doc.meta.loop) == ("implement", 2)
    assert doc.sections["Findings"].startswith(f"- high · -:0 · {BOOM_HEADLINE} · ")
    assert doc.sections["Check output"].startswith(f"{BOOM_HEADLINE}\n```text\n")
    assert engine.state().sent_back == SentBack(step="run_tests", summary="tests failed (exit 1)")
    doc.meta.status = "in_process/under_implementation"  # what `kengash run` does
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    steps.run_job("7b55e0c1", steps=1)
    prompt = fake_clis.calls("codex")[1]["argv"][-1]
    assert "run_tests sent this back: tests failed (exit 1). Fix every Finding below" in prompt
    assert "## Check output" in prompt


def test_a_passing_check_clears_check_output(engine: Engine, fake_clis: FakeClis) -> None:
    write_settings(
        engine.paths,
        checks_settings("test -f fixed.txt || { echo 'error: boom'; exit 1; }", turns=0),
    )
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"retry.py": "r = 3\n"})
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"fixed.txt": "ok\n"})
    steps.run_job("7b55e0c1", steps=5)
    doc = engine.ticket()
    assert doc.meta.step == "review_code"
    assert doc.sections.get("Check output", "") == ""


def test_the_next_step_consumes_sent_back(engine: Engine, fake_clis: FakeClis) -> None:
    write_settings(engine.paths, checks_settings(BOOM, turns=0))
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"retry.py": "r = 3\n"})
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"retry.py": "r = 4\n"})
    steps.run_job("7b55e0c1", steps=4)
    assert engine.ticket().meta.step == "run_tests"
    assert engine.state().sent_back is None


FIXED = "test -f fixed.txt || { echo 'error: fixed.txt missing'; exit 1; }"


def check_runs(events: Events) -> list[tuple[int, str]]:
    return [(e["turn"], e["verdict"]) for e in events() if e["type"] == "checks.end"]


def queue_plan_and_implement(fake_clis: FakeClis, *edits: dict[str, str]) -> None:
    """The plan reply, then one implementer reply per `edits` (first turn, then fix turns)."""
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    for change in edits:
        fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits=change)


def test_checks_pass_first_time_with_no_fix_turn(
    engine: Engine, fake_clis: FakeClis, journal_events: Events
) -> None:
    write_settings(engine.paths, checks_settings(FIXED))
    queue_plan_and_implement(fake_clis, {"fixed.txt": "ok\n"})
    steps.run_job("7b55e0c1", steps=2)
    assert check_runs(journal_events) == [(0, "pass")]
    log = engine.ticket().sections["Log"]
    assert "· checks · kengash · shell/default · pass · 0 · tests passed" in log
    assert len(fake_clis.calls("codex")) == 1


def test_a_failing_check_gets_a_fix_turn_in_the_same_loop(
    engine: Engine, fake_clis: FakeClis, journal_events: Events, run_git: Callable[..., str]
) -> None:
    write_settings(engine.paths, checks_settings(FIXED))
    queue_plan_and_implement(fake_clis, {"a.txt": "a\n"}, {"fixed.txt": "ok\n"})
    steps.run_job("7b55e0c1", steps=2)
    _, fix = fake_clis.calls("codex")
    assert fix["argv"][:2] == ["exec", "resume"]
    assert "fix turn 1 of 2" in fix["argv"][-1] and "error: fixed.txt missing" in fix["argv"][-1]
    assert check_runs(journal_events) == [(0, "fail"), (1, "pass")]
    doc = engine.ticket()
    assert (doc.meta.step, doc.meta.loop) == ("run_tests", 1)
    assert doc.sections.get("Check output", "") == ""
    files = run_git(engine.worktree, "show", "--name-only", "--format=", "HEAD").split()
    assert {"a.txt", "fixed.txt"} <= set(files)


def test_when_fix_turns_run_out_run_tests_sends_it_back(
    engine: Engine, fake_clis: FakeClis, journal_events: Events
) -> None:
    write_settings(engine.paths, checks_settings(FIXED, turns=1))
    queue_plan_and_implement(fake_clis, {"a.txt": "a\n"}, {"b.txt": "b\n"})
    steps.run_job("7b55e0c1", steps=3)
    doc = engine.ticket()
    assert (doc.meta.step, doc.meta.loop) == ("implement", 2)
    assert "error: fixed.txt missing" in doc.sections["Findings"]
    assert check_runs(journal_events)[:2] == [(0, "fail"), (1, "fail")]


@pytest.mark.parametrize(
    "settings_text", [checks_settings(FIXED, run_tests=False), checks_settings(FIXED, turns=0)]
)
def test_no_check_step_or_zero_turns_means_no_in_step_checks(
    engine: Engine, fake_clis: FakeClis, journal_events: Events, settings_text: str
) -> None:
    write_settings(engine.paths, settings_text)
    queue_plan_and_implement(fake_clis, {"a.txt": "a\n"})
    steps.run_job("7b55e0c1", steps=2)
    assert check_runs(journal_events) == []
    assert len(fake_clis.calls("codex")) == 1


def test_a_network_error_in_a_fix_turn_resumes_once(
    engine: Engine, fake_clis: FakeClis, journal_events: Events
) -> None:
    write_settings(engine.paths, checks_settings(FIXED))
    queue_plan_and_implement(fake_clis, {"a.txt": "a\n"})
    fake_clis.queue("codex", stdout=_codex_cut(), exit=1)
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"fixed.txt": "ok\n"})
    steps.run_job("7b55e0c1", steps=2)
    assert fake_clis.calls("codex")[2]["argv"][-1] == prompts.NETWORK_PROMPT
    assert check_runs(journal_events) == [(0, "fail"), (1, "pass")]


def test_an_invalid_fix_reply_keeps_the_last_valid_one(
    engine: Engine, fake_clis: FakeClis, journal_events: Events
) -> None:
    write_settings(engine.paths, checks_settings(FIXED))
    queue_plan_and_implement(fake_clis, {"a.txt": "a\n"})
    fake_clis.queue("codex", stdout=fake_clis.codex_output({"summary": "s"}))
    steps.run_job("7b55e0c1", steps=2)
    doc = engine.ticket()
    assert doc.meta.status != "in_process/failed" and doc.meta.step == "run_tests"
    handoff = fake_clis.fixture("codex/work_resume.jsonl")
    assert doc.sections["Handoff"] and doc.sections["Handoff"] in handoff
    assert check_runs(journal_events) == [(0, "fail")]


def test_a_hanging_check_ends_the_in_step_checks(
    engine: Engine, fake_clis: FakeClis, journal_events: Events, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(calls, "step_timeout", lambda resolved: 1)
    write_settings(engine.paths, checks_settings("sleep 5"))
    queue_plan_and_implement(fake_clis, {"a.txt": "a\n"})
    steps.run_job("7b55e0c1", steps=2)
    assert check_runs(journal_events) == [(0, "timeout")]
    assert len(fake_clis.calls("codex")) == 1


def test_a_ticket_moved_during_checks_gets_no_fix_turn(
    engine: Engine, fake_clis: FakeClis, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kengash_ai.adapters.shell import Shell
    from kengash_ai.ops import controls

    real = Shell.run

    def park_then_fail(self: Shell, req: StepRequest) -> StepResult:
        controls.park_ticket("7b55e0c1", "user took it", project=None, by="test")
        return real(self, req)

    monkeypatch.setattr(Shell, "run", park_then_fail)
    write_settings(engine.paths, checks_settings(FIXED))
    queue_plan_and_implement(fake_clis, {"a.txt": "a\n"})
    steps.run_job("7b55e0c1", steps=2)
    assert len(fake_clis.calls("codex")) == 1
    assert engine.ticket().meta.status == "in_queue/parked"


def counted(engine: Engine) -> tuple[str, Path]:
    """FIXED that also counts its runs in a file outside the worktree."""
    runs = engine.repo.parent / "runs"
    return f"echo x >> {runs}; {FIXED}", runs


def test_run_tests_reuses_a_passing_in_step_result(
    engine: Engine, fake_clis: FakeClis, journal_events: Events
) -> None:
    command, runs = counted(engine)
    write_settings(engine.paths, checks_settings(command))
    queue_plan_and_implement(fake_clis, {"fixed.txt": "ok\n"})
    steps.run_job("7b55e0c1", steps=3)
    assert len(runs.read_text().splitlines()) == 1
    assert engine.ticket().meta.step == "review_code"
    assert "· run_tests · test-runner · shell/default · pass · 0" in engine.ticket().sections["Log"]
    [ended] = [e for e in journal_events() if e["type"] == "step.end" and e["step"] == "run_tests"]
    assert ended["duration_s"] == 0


@pytest.mark.parametrize("change", ["dirty", "commit"])
def test_run_tests_reruns_on_a_dirty_worktree_or_a_new_commit(
    engine: Engine, fake_clis: FakeClis, run_git: Callable[..., str], change: str
) -> None:
    command, runs = counted(engine)
    write_settings(engine.paths, checks_settings(command))
    queue_plan_and_implement(fake_clis, {"fixed.txt": "ok\n"})
    steps.run_job("7b55e0c1", steps=2)
    (engine.worktree / "extra.txt").write_text("x\n", encoding="utf-8")
    if change == "commit":
        run_git(engine.worktree, "add", "extra.txt")
        run_git(engine.worktree, "commit", "-qm", "by hand")
    doc = engine.ticket()
    doc.meta.status = "in_process/under_test"
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    steps.run_job("7b55e0c1", steps=1)
    assert len(runs.read_text().splitlines()) == 2


def test_a_failing_in_step_result_is_never_reused(engine: Engine, fake_clis: FakeClis) -> None:
    command, runs = counted(engine)
    write_settings(engine.paths, checks_settings(command, turns=1))
    queue_plan_and_implement(fake_clis, {"a.txt": "a\n"}, {"b.txt": "b\n"})
    steps.run_job("7b55e0c1", steps=3)
    assert len(runs.read_text().splitlines()) == 3  # turn 0, turn 1, then run_tests


def test_a_hook_repair_turn_disables_reuse(engine: Engine, fake_clis: FakeClis) -> None:
    hook = engine.repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\ntest -f hooked || { echo 'lint: add hooked'; exit 1; }\n")
    hook.chmod(0o755)
    command, runs = counted(engine)
    write_settings(engine.paths, checks_settings(command))
    queue_plan_and_implement(fake_clis, {"fixed.txt": "ok\n"}, {"hooked": "yes\n"})
    steps.run_job("7b55e0c1", steps=3)
    assert engine.ticket().meta.step == "review_code"
    assert len(runs.read_text().splitlines()) == 2


def test_a_blocked_plan_stops_the_ticket(
    engine: Engine, fake_clis: FakeClis, journal_events: Events
) -> None:
    handoff = "Files: a.py\nBLOCKED: the design assets need the user's claude.ai login"
    fake_clis.queue(
        "claude", stdout=fake_clis.claude_output({"summary": "Plan", "handoff": handoff})
    )
    reason = "blocked: the design assets need the user's claude.ai login"
    assert steps.run_job("7b55e0c1") == JobEnd("in_process/needs_approval", reason)
    doc = engine.ticket()
    assert (doc.meta.step, doc.meta.loop) == ("plan", 1)
    assert engine.state().approval == "blocked"
    assert "ticket.needs_approval" in [e["type"] for e in journal_events()]


def test_blocked_implement_commits_its_work_first(
    engine: Engine, fake_clis: FakeClis, run_git: Callable[..., str]
) -> None:
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    partial = fake_clis.codex_output({"summary": "Partial", "handoff": "BLOCKED: no pyftsubset"})
    fake_clis.queue("codex", stdout=partial, edits={"a.py": "x = 1\n"})
    end = steps.run_job("7b55e0c1")
    assert end == JobEnd("in_process/needs_approval", "blocked: no pyftsubset")
    assert "a.py" in run_git(engine.worktree, "show", "--name-only", "--format=", "HEAD")
    assert engine.ticket().meta.step == "implement"


@pytest.mark.parametrize(
    "reply",
    [{"stdout": "", "stderr": "segfault", "exit": 1}, {"fixture": "codex/usage_limit.jsonl"}],
)
def test_a_failed_fix_turn_keeps_the_step(
    engine: Engine, fake_clis: FakeClis, journal_events: Events, reply: dict[str, Any]
) -> None:
    # review finding: fix turns only add chances; an error in one never fails the step
    write_settings(engine.paths, checks_settings(FIXED, turns=1) + "fallback_on_error: false\n")
    queue_plan_and_implement(fake_clis, {"a.txt": "a\n"})
    fake_clis.queue("codex", **reply)
    steps.run_job("7b55e0c1", steps=2)
    doc = engine.ticket()
    assert doc.meta.status != "in_process/failed" and doc.meta.step == "run_tests"
    assert doc.sections["Handoff"] == "retry.py retries 3 times with exponential backoff."
    assert check_runs(journal_events) == [(0, "fail")]


def test_a_park_during_checks_stops_the_fix_turns(
    engine: Engine, fake_clis: FakeClis, monkeypatch: pytest.MonkeyPatch
) -> None:
    # review finding: with a live worker, park only sets a flag
    from kengash_ai.adapters.shell import Shell
    from kengash_ai.model import WorkerRecord
    from kengash_ai.ops import controls

    runtime.save_worker(
        engine.paths, WorkerRecord(id="7b55e0c1", project=engine.slug, pid=os.getpid())
    )
    real = Shell.run

    def park_then_run(self: Shell, req: StepRequest) -> StepResult:
        assert controls.park_ticket("7b55e0c1", "user took it", project=None, by="t").deferred
        return real(self, req)

    monkeypatch.setattr(Shell, "run", park_then_run)
    write_settings(engine.paths, checks_settings(FIXED))
    queue_plan_and_implement(fake_clis, {"a.txt": "a\n"})
    steps.run_job("7b55e0c1", steps=3)
    assert len(fake_clis.calls("codex")) == 1
    assert engine.ticket().meta.status == "in_queue/parked"


def test_a_blocked_reply_skips_the_checks(
    engine: Engine, fake_clis: FakeClis, journal_events: Events
) -> None:
    write_settings(engine.paths, checks_settings(FIXED))
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    blocked = fake_clis.codex_output({"summary": "Partial", "handoff": "BLOCKED: no assets"})
    fake_clis.queue("codex", stdout=blocked)
    assert steps.run_job("7b55e0c1").status == "in_process/needs_approval"
    assert check_runs(journal_events) == []


def test_a_check_failure_at_the_loop_cap_still_says_why(
    engine: Engine, fake_clis: FakeClis
) -> None:
    write_settings(engine.paths, checks_settings(BOOM, turns=0))
    doc = engine.ticket()
    doc.meta.loop_max = 1
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    queue_plan_and_implement(fake_clis, {"a.txt": "a\n"})
    assert steps.run_job("7b55e0c1").status == "in_process/needs_approval"
    assert engine.state().sent_back == SentBack(step="run_tests", summary="tests failed (exit 1)")


@pytest.mark.parametrize(("turns", "budget"), [(0, 3), (1, 2)])
def test_check_output_is_redacted(
    engine: Engine, fake_clis: FakeClis, turns: int, budget: int
) -> None:
    leaky = "echo 'error: token=abc123def456ghi789'; exit 1"
    write_settings(engine.paths, checks_settings(leaky, turns=turns))
    queue_plan_and_implement(fake_clis, {"a.txt": "a\n"}, {"b.txt": "b\n"})
    steps.run_job("7b55e0c1", steps=budget)
    output = engine.ticket().sections["Check output"]
    assert "abc123def456ghi789" not in output and "[REDACTED]" in output


def test_files_the_checks_create_are_not_committed(
    engine: Engine, fake_clis: FakeClis, run_git: Callable[..., str]
) -> None:
    golden = "mkdir -p test/failures && echo png > test/failures/golden.png; "
    write_settings(engine.paths, checks_settings(golden + FIXED))
    queue_plan_and_implement(fake_clis, {"a.txt": "a\n"}, {"fixed.txt": "ok\n"})
    steps.run_job("7b55e0c1", steps=2)
    files = run_git(engine.worktree, "show", "--name-only", "--format=", "HEAD").split()
    assert "fixed.txt" in files and "test/failures/golden.png" not in files
    assert not (engine.worktree / "test" / "failures" / "golden.png").exists()


def test_the_implementer_session_survives_a_check_run(
    engine: Engine, fake_clis: FakeClis, monkeypatch: pytest.MonkeyPatch
) -> None:
    # review finding: a worker killed during checks must not lose the new session
    from kengash_ai import gitops
    from kengash_ai.adapters.shell import Shell

    sessions: list[Any] = []
    roles: list[str] = []
    real_run, real_commit = Shell.run, gitops.commit_all

    def spy_run(self: Shell, req: StepRequest) -> StepResult:
        sessions.append(engine.ticket().meta.sessions.get("implementer"))
        return real_run(self, req)

    def spy_commit(*args: Any, **kwargs: Any) -> Any:
        running = engine.state().running
        roles.append(running.role if running else "")
        return real_commit(*args, **kwargs)

    monkeypatch.setattr(Shell, "run", spy_run)
    monkeypatch.setattr(gitops, "commit_all", spy_commit)
    write_settings(engine.paths, checks_settings(FIXED))
    queue_plan_and_implement(fake_clis, {"fixed.txt": "ok\n"})
    steps.run_job("7b55e0c1", steps=2)
    assert sessions and sessions[0] is not None
    assert sessions[0].id == "0199a213-81c0-7800-8aa1-bbab2a035a53"
    assert roles == ["implementer"]


def test_new_session_prompt_carries_project_memory(engine: Engine, fake_clis: FakeClis) -> None:
    process = engine.paths.project("payments-api").process
    process.write_text("# PROCESS.md\n\n## Process notes\n\n- money is integer cents\n")
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    steps.run_job("7b55e0c1", steps=1)
    prompt = fake_clis.calls("claude")[0]["argv"][1]
    assert prompt.index("## Memory") < prompt.index("## Goal")
    assert "- money is integer cents" in prompt


def test_work_reply_decisions_wait_for_the_merge(engine: Engine, fake_clis: FakeClis) -> None:
    proposal = {"decision": "retries use full jitter", "why": "herd", "rejected": ""}
    reply = {"summary": "Planned.", "handoff": "h", "files": [], "decisions": [proposal]}
    fake_clis.queue("claude", stdout=fake_clis.claude_output(reply))
    steps.run_job("7b55e0c1", steps=1)
    assert engine.ticket().sections["Decisions"] == "- retries use full jitter. why: herd."
    decisions = (engine.paths.memory / "DECISIONS.md").read_text(encoding="utf-8")
    assert "full jitter" not in decisions


def _holder(engine: Engine, make_ticket: Callable[..., Doc[Ticket]]) -> None:
    holder = make_ticket(
        "c0ffee00",
        status="in_process/under_implementation",
        step="implement",
        workflow="simple",
        importance="simple",
        touches=engine.ticket().meta.touches,
    )
    documents.save_ticket(engine.paths.project(engine.slug), holder)


def _move(engine: Engine, ticket_id: str, status: str) -> None:
    project = engine.paths.project(engine.slug)
    path = documents.find_ticket(project, ticket_id)
    assert path is not None
    doc = documents.load_ticket(path)
    doc.meta.status = status
    documents.save_ticket(project, doc)


def test_job_waits_for_overlapping_holder_then_runs(
    engine: Engine,
    fake_clis: FakeClis,
    make_ticket: Callable[..., Doc[Ticket]],
    monkeypatch: pytest.MonkeyPatch,
    journal_events: Events,
) -> None:
    _holder(engine, make_ticket)
    naps: list[float] = []

    def nap(seconds: float) -> None:
        naps.append(seconds)
        assert engine.ticket().meta.status == "in_process/waiting_paths"
        if len(naps) == 2:
            _move(engine, "c0ffee00", "in_process/needs_approval")  # a gate lets go

    monkeypatch.setattr(steps, "sleep", nap)
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"retry.py": "x = 1\n"})
    steps.run_job("7b55e0c1", steps=2)
    assert naps == [steps.PATH_POLL_S, steps.PATH_POLL_S]
    waited = [e for e in journal_events() if e["type"] == "ticket.waiting"]
    assert [(e["holder"], e["reason"]) for e in waited] == [
        ("c0ffee00", "touches overlap c0ffee00")
    ]
    assert len(fake_clis.calls("codex")) == 1 and engine.state().waiting_on == ""


def test_job_enters_editing_without_wait_when_free(
    engine: Engine, fake_clis: FakeClis, monkeypatch: pytest.MonkeyPatch
) -> None:
    naps: list[float] = []
    monkeypatch.setattr(steps, "sleep", naps.append)
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"retry.py": "x = 1\n"})
    steps.run_job("7b55e0c1", steps=2)
    assert naps == [] and len(fake_clis.calls("codex")) == 1


def test_park_while_waiting_paths(
    engine: Engine,
    fake_clis: FakeClis,
    make_ticket: Callable[..., Doc[Ticket]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _holder(engine, make_ticket)
    monkeypatch.setattr(
        steps, "sleep", lambda _: runtime.set_park(engine.paths, "7b55e0c1", on=True)
    )
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    assert steps.run_job("7b55e0c1").status == "in_queue/parked"
    assert fake_clis.calls("codex") == []


def test_implement_starts_from_newest_base(
    engine: Engine, fake_clis: FakeClis, run_git: Callable[..., str]
) -> None:
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    steps.run_job("7b55e0c1", steps=1)  # planned on the old main
    _move(engine, "7b55e0c1", "in_process/waiting_paths")  # undo the step budget's pause
    (engine.repo / "merged.py").write_text("from another ticket\n")
    gitops.commit_all(engine.repo, "another ticket merged", {})
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"retry.py": "x = 1\n"})
    steps.run_job("7b55e0c1", steps=1)
    assert (engine.worktree / "merged.py").exists()
    log = run_git(engine.worktree, "log", "--format=%s", "-2").splitlines()
    assert log[1] == "another ticket merged"
