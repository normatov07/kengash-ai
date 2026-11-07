"""Plan review: the reviewer's provider, the review job and its rounds (SP3 spec decisions
14, 28 to 30)."""

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import Events, FakeClis, write_settings

from kengash_ai import settings
from kengash_ai.model import (
    Doc,
    NeedsSetup,
    Plan,
    PlanMode,
    PlanStatus,
    ProviderStatus,
    WorkerRecord,
)
from kengash_ai.ops import calls, jobs, plans, records, reviews
from kengash_ai.ops.agents import Pick
from kengash_ai.store import StorePaths, documents, runtime

SECTIONS = (
    "## Goal\nWebhook keys rotate without downtime.\n"
    "## Scope\nA keyring of signing keys.\n"
    "## Design\nTwo active keys; the newest signs.\n"
    "## Acceptance\n- [ ] an old key verifies for 48h\n"
)
FINDING = {
    "severity": "medium",
    "file": "Design",
    "line": 0,
    "issue": "no key expiry",
    "fix": "add a 48h expiry",
}
FAIL = {"verdict": "fail", "summary": "Keys never expire.", "findings": [FINDING]}
PASS = {"verdict": "pass", "summary": "Sound plan.", "findings": []}
SESSION = "0f0d6091-da14-49d7-8ca3-ab7d531f4132"  # claude/review_new.json


def status(**usable: bool) -> Callable[[str], ProviderStatus]:
    def detect(name: str) -> ProviderStatus:
        ok = usable.get(name, True)
        return ProviderStatus(name=name, installed=ok, signed_in=ok, hint=f"install {name}")

    return detect


def load(paths: StorePaths, plan_id: str) -> Doc[Plan]:
    _, path = records.locate_plan(paths, plan_id, None)
    return records.load_plan(path)


def reviewing(paths: StorePaths, plan_id: str, reviewer: str = "claude/haiku") -> None:
    """Leave the plan as `plan review` does before it starts the job."""
    doc = load(paths, plan_id)
    doc.meta.status = PlanStatus.in_review
    doc.meta.review.reviewer = reviewer
    doc.meta.review.verdict = None
    documents.save_plan(paths.project(doc.meta.project), doc)


@pytest.fixture
def plan_id(registered_repo: Path, store_paths: StorePaths) -> str:
    made = plans.new_plan(
        "Make webhook keys rotatable.",
        title="Rotatable keys",
        mode=PlanMode.direct,
        project=None,
        cwd=registered_repo,
        by="user",
    )
    plans.save_plan(made.id, SECTIONS, project=None, by="user")
    reviewing(store_paths, made.id)
    return made.id


def prompt_of(call: dict[str, Any]) -> str:
    argv = call["argv"]
    return str(argv[argv.index("-p") + 1])


def test_conductor_provider_reads_by_then_claudecode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLAUDECODE", raising=False)
    assert [reviews.conductor_provider(by) for by in ("agy", "codex", "claude", "unknown")] == [
        "antigravity",
        "codex",
        "claude",
        None,
    ]
    monkeypatch.setenv("CLAUDECODE", "1")
    assert reviews.conductor_provider("unknown") == "claude"
    assert reviews.conductor_provider("user") is None


def test_choose_reviewer_avoids_the_conductors_provider(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    write_settings(
        store_paths,
        "agents:\n  plan-reviewer: {cli: claude, skill: review-plan, "
        "fallback: [antigravity/gemini-3.8-flash-low]}\n",
    )
    resolved = settings.load(store_paths, "payments-api")
    agy = Pick("plan-reviewer", "antigravity", "gemini-3.8-flash-low", True)
    assert reviews.choose_reviewer(resolved, "claude", status()) == (agy, "")
    assert reviews.choose_reviewer(resolved, "codex", status())[0].provider == "claude"
    assert reviews.choose_reviewer(resolved, None, status())[0].provider == "claude"


def test_choose_reviewer_takes_another_signed_in_provider(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    write_settings(store_paths, "agents:\n  plan-reviewer: {cli: claude, skill: review-plan}\n")
    resolved = settings.load(store_paths, "payments-api")
    pick, warning = reviews.choose_reviewer(resolved, "claude", status(codex=False))
    assert (pick.provider, pick.model, warning) == ("antigravity", None, "")


def test_choose_reviewer_warns_when_only_the_conductors_provider_is_usable(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    write_settings(store_paths, "agents:\n  plan-reviewer: {cli: claude, skill: review-plan}\n")
    resolved = settings.load(store_paths, "payments-api")
    pick, warning = reviews.choose_reviewer(
        resolved, "claude", status(codex=False, antigravity=False)
    )
    assert pick.provider == "claude" and "no other provider" in warning
    with pytest.raises(NeedsSetup):
        reviews.choose_reviewer(
            resolved, "claude", status(claude=False, codex=False, antigravity=False)
        )


def test_a_named_reviewer_is_used_directly(registered_repo: Path, store_paths: StorePaths) -> None:
    write_settings(store_paths, "plan.reviewer: antigravity/gemini-3.8-flash-low\n")
    resolved = settings.load(store_paths, "payments-api")
    pick, _ = reviews.choose_reviewer(resolved, "antigravity", status())
    assert (pick.provider, pick.model) == ("antigravity", "gemini-3.8-flash-low")
    with pytest.raises(NeedsSetup, match="antigravity"):
        reviews.choose_reviewer(resolved, None, status(antigravity=False))


def test_a_review_round_records_verdict_session_and_review_log(
    plan_id: str,
    store_paths: StorePaths,
    registered_repo: Path,
    fake_clis: FakeClis,
    journal_events: Events,
) -> None:
    fake_clis.queue("claude", stdout=fake_clis.claude_output(FAIL))
    assert reviews.run_review(plan_id, project=None) == f"{plan_id}: round 1 fail"
    doc = load(store_paths, plan_id)
    review = doc.meta.review
    assert (doc.meta.status, review.round, review.verdict) == (PlanStatus.in_review, 1, "fail")
    assert review.session is not None
    assert (review.session.provider, review.session.model, review.session.id) == (
        "claude",
        "haiku",
        SESSION,
    )
    assert (
        doc.sections["Review log"]
        == "- round 1 · medium · Design:0 · no key expiry · add a 48h expiry"
    )
    (call,) = fake_clis.calls("claude")
    assert call["cwd"] == str(registered_repo)
    assert "dontAsk" in call["argv"] and call["argv"][call["argv"].index("--model") + 1] == "haiku"
    prompt = prompt_of(call)
    assert "round 1 of 2" in prompt and "## Prompt" in prompt
    assert "Webhook keys rotate without downtime." in prompt and "## Review log" not in prompt
    event = journal_events()[-1]
    assert event["type"] == "plan.reviewed"
    assert (event["round"], event["max"], event["verdict"], event["findings"]) == (1, 2, "fail", 1)
    assert event["reviewer"] == "claude/haiku" and event["session"] == SESSION
    assert runtime.load_slots(store_paths).held == []


def test_the_next_round_resumes_the_reviewer_session(
    plan_id: str, store_paths: StorePaths, fake_clis: FakeClis
) -> None:
    fake_clis.queue("claude", stdout=fake_clis.claude_output(FAIL))
    reviews.run_review(plan_id, project=None)
    reviewing(store_paths, plan_id)  # the planner saved a revision; review again
    fake_clis.queue("claude", stdout=fake_clis.claude_output(PASS))
    assert reviews.run_review(plan_id, project=None) == f"{plan_id}: round 2 pass"
    second = fake_clis.calls("claude")[1]
    assert second["argv"][second["argv"].index("--resume") + 1] == SESSION
    prompt = prompt_of(second)
    assert prompt.startswith("Round 2 of 2") and "## Review log" in prompt
    log = load(store_paths, plan_id).sections["Review log"].splitlines()
    assert log[-1] == "- round 2 · pass · Sound plan."


def test_a_failed_call_ends_the_job_without_a_round(
    plan_id: str, store_paths: StorePaths, fake_clis: FakeClis, journal_events: Events
) -> None:
    fake_clis.queue("claude", fixture="claude/auth_error.json")
    reviews.run_review(plan_id, project=None)
    review = load(store_paths, plan_id).meta.review
    assert (review.round, review.verdict) == (0, None)
    event = journal_events()[-1]
    assert (event["type"], event["job"], event["plan"], event["ok"]) == (
        "worker.exited",
        "plan-review",
        plan_id,
        False,
    )
    assert event["reason"] == "sign in to claude interactively"
    assert runtime.load_slots(store_paths).held == []


def test_a_plan_saved_during_the_round_keeps_the_users_version(
    plan_id: str,
    store_paths: StorePaths,
    fake_clis: FakeClis,
    journal_events: Events,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = calls.call

    def saving(*args: Any, **kwargs: Any) -> calls.Called:
        plans.save_plan(plan_id, "## Risks\nKey leaks.\n", project=None, by="user")
        return real(*args, **kwargs)

    monkeypatch.setattr(calls, "call", saving)
    fake_clis.queue("claude", stdout=fake_clis.claude_output(FAIL))
    reviews.run_review(plan_id, project=None)
    doc = load(store_paths, plan_id)
    assert (doc.meta.status, doc.meta.review.round) == (PlanStatus.draft, 0)
    assert doc.sections.get("Review log", "") == ""
    event = journal_events()[-1]
    assert event["type"] == "worker.exited" and "changed" in event["reason"]


def _stand_in_worker(paths: StorePaths, plan_id: str) -> None:
    """This test process plays the review worker: its record names our live pid."""
    data = {"id": plan_id, "project": "", "pid": os.getpid(), "job": "plan-review"}
    runtime.save_worker(paths, WorkerRecord.model_validate(data))


def test_a_finished_round_drops_the_workers_record_with_its_verdict(
    plan_id: str, store_paths: StorePaths, fake_clis: FakeClis
) -> None:
    # as for compaction (CI 2026-11-07): the next `plan review` must not join a worker
    # that has journaled its round but not yet exited
    _stand_in_worker(store_paths, plan_id)
    fake_clis.queue("claude", stdout=fake_clis.claude_output(FAIL))
    reviews.run_review(plan_id, project=None)
    assert jobs.alive(store_paths, plan_id) is None


def test_a_failed_round_drops_the_workers_record_with_its_end(
    plan_id: str, store_paths: StorePaths, fake_clis: FakeClis
) -> None:
    _stand_in_worker(store_paths, plan_id)
    fake_clis.queue("claude", fixture="claude/auth_error.json")
    reviews.run_review(plan_id, project=None)
    assert jobs.alive(store_paths, plan_id) is None
