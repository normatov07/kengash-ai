"""The relay covers live loops, contracts, escalation and stats (SP20 spec)."""

import os
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import Engine, FakeClis
from typer.testing import CliRunner

from kengash_ai import journal, settings
from kengash_ai.cli import app
from kengash_ai.model import Doc, Event, LoopLease, PlanMode, ProviderStatus, Ticket, UserError
from kengash_ai.ops import agents, controls, plans, records, relay, stats, tickets
from kengash_ai.store import StorePaths, documents, runtime

runner = CliRunner()
Make = Callable[..., Doc[Ticket]]
BATCH = """\
- key: core
  title: Core
  importance: standard
  provides: ["Core.run() -> None"]
- key: left
  title: Left
  importance: standard
  depends_on: [core]
  needs: {core: runs it}
"""


def plan_for(repo: Path) -> str:
    made = plans.new_plan("Do it.", title="P", mode=PlanMode.direct, project=None, cwd=repo, by="x")
    plans.approve_plan(made.id, skip_review=True, project=None, by="x")
    return made.id


def lease(paths: StorePaths, project: str | None = None) -> None:
    runtime.save_lease(
        paths, LoopLease(pid=os.getpid(), agent="claude", project=project, command="")
    )


def test_a_live_lease_is_enough_for_the_relay(
    store_paths: StorePaths,
    inside_registered_repo: Path,
    make_ticket: Make,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    documents.save_ticket(store_paths.project("payments-api"), make_ticket())
    lease(store_paths)
    started: list[list[str]] = []

    def run(ids: list[str], *, project: None, by: str) -> Any:
        started.append(list(ids))
        return SimpleNamespace(started=[])

    monkeypatch.setattr(controls, "run_tickets", run)
    relay.advance(store_paths)
    assert started == [["7b55e0c1"]]


def test_no_loop_means_no_relay(
    store_paths: StorePaths,
    inside_registered_repo: Path,
    make_ticket: Make,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    documents.save_ticket(store_paths.project("payments-api"), make_ticket())
    monkeypatch.setattr(controls, "run_tickets", lambda *a, **k: pytest.fail("started"))
    assert relay.advance(store_paths) == []


def test_ticket_add_advances_the_relay(
    inside_registered_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[bool] = []

    def advance() -> list[str]:
        called.append(True)
        return []

    monkeypatch.setattr(relay, "advance_quietly", advance)
    plan = plan_for(inside_registered_repo)
    assert runner.invoke(app, ["ticket", "add", "--plan", plan], input=BATCH).exit_code == 0
    assert called == [True]


def test_a_relied_on_ticket_must_promise_something(registered_repo: Path) -> None:
    batch = BATCH.replace('  provides: ["Core.run() -> None"]\n', "")
    with pytest.raises(UserError, match="list in `provides`"):
        tickets.add_tickets(plan_for(registered_repo), batch, project=None, by="x")


def test_the_contract_lands_in_both_scopes(store_paths: StorePaths, registered_repo: Path) -> None:
    batch = tickets.add_tickets(plan_for(registered_repo), BATCH, project=None, by="x")
    ids = {new.key: new.id for new in batch.tickets}

    def text(key: str | None) -> str:
        _, path = records.locate_ticket(store_paths, ids[key], None)
        return path.read_text(encoding="utf-8")

    assert "Provides, exactly as written:\n- Core.run() -> None" in text("core")
    assert f"- {ids['core']}: runs it\n  - promised: Core.run() -> None" in text("left")


def usable(name: str) -> ProviderStatus:
    return ProviderStatus(name=name, installed=True, signed_in=True)


@pytest.fixture
def ladder(engine: Engine) -> Any:
    changes = {
        "agents.implementer.cli": "claude/sonnet",
        "agents.implementer.fallback": [],
        "agents.implementer.escalate": ["claude/opus", "claude/fable"],
    }
    settings.set_values(engine.paths, engine.slug, changes)
    return settings.load(engine.paths, engine.slug)


@pytest.mark.parametrize(
    ("loop", "model"), [(1, "sonnet"), (2, "opus"), (3, "fable"), (6, "fable")]
)
def test_a_failed_attempt_gets_a_stronger_model(ladder: Any, loop: int, model: str) -> None:
    pick = agents.pick(ladder, "implementer", usable, loop=loop)
    assert (pick.model, pick.fallback) == (model, False)


def test_an_unusable_escalation_falls_to_the_normal_chain(ladder: Any) -> None:
    pick = agents.pick(ladder, "implementer", usable, loop=2, skip={"claude/opus"})
    assert (pick.model, pick.fallback) == ("sonnet", False)


def test_no_ladder_changes_nothing(engine: Engine) -> None:
    resolved = settings.load(engine.paths, engine.slug)
    assert agents.pick(resolved, "planner", usable, loop=5).model == "opus"


def test_a_step_runs_on_the_escalated_model(
    engine: Engine, fake_clis: FakeClis, ladder: Any
) -> None:
    from kengash_ai.ops import steps

    doc = engine.ticket()
    doc.meta.loop, doc.meta.status, doc.meta.step = (
        2,
        "in_process/under_implementation",
        "implement",
    )
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    fake_clis.queue("claude", fixture="claude/work_resume.json", edits={"a.py": "x = 1\n"})
    steps.run_job("7b55e0c1", steps=1)
    argv = fake_clis.calls("claude")[0]["argv"]
    assert argv[argv.index("--model") + 1] == "opus"


def event(kind: str, ticket: str, at: str, **extra: Any) -> Event:
    data = {"type": kind, "project": "app", "ticket": ticket, "ts": f"2026-11-09T{at}:00Z", **extra}
    return Event.model_validate(data)


def test_stats_counts_parallelism_yield_tokens_and_gates(
    monkeypatch: pytest.MonkeyPatch, store_paths: StorePaths
) -> None:
    def end(
        ticket: str, at: str, role: str, verdict: str = "pass", step: str = "implement"
    ) -> Event:
        tokens = {"in": 100, "out": 50}
        return event(
            "step.end",
            ticket,
            at,
            step=step,
            role=role,
            provider="claude",
            model="sonnet",
            verdict=verdict,
            tokens=tokens,
        )

    events = [
        event("step.start", "a", "10:00", step="implement"),
        event("step.start", "b", "10:05", step="implement"),
        end("a", "10:10", "implementer"),
        end("b", "10:20", "implementer"),
        end("a", "10:21", "code-reviewer", "fail", "review_code"),
        end("b", "10:22", "code-reviewer", "pass", "review_code"),
        event("ticket.merged", "b", "10:30", loop=1),
        event("ticket.needs_approval", "a", "10:31", reason="loop cap: 4 of 4"),
        event("ticket.needs_approval", "a", "10:32", reason="conflict in a.py, b.py"),
        Event.model_validate({"type": "step.end", "project": "other", "ticket": "z", "role": "x"}),
    ]
    monkeypatch.setattr(journal, "read", lambda paths, since: iter(events))
    found = stats.compute(store_paths, "app", 7)
    assert found.minutes == {1: 15, 2: 5}
    assert round(found.mean_workers, 2) == 1.25
    assert (found.merged, found.first_pass) == (1, 1)
    (row,) = found.models
    assert (row.cli, row.runs, row.reviewed, row.passed) == ("claude/sonnet", 2, 2, 1)
    assert found.gates == {"loop cap": 1, "conflict": 1}


def test_stats_does_not_count_a_quota_wait_as_work(
    monkeypatch: pytest.MonkeyPatch, store_paths: StorePaths
) -> None:
    events = [
        event("step.start", "a", "10:00", step="plan"),
        event("step.quota_wait", "a", "10:02", step="plan"),
        event("step.quota_resume", "a", "13:02", step="plan"),
        event("step.end", "a", "13:05", step="plan", role="planner", verdict="pass"),
    ]
    monkeypatch.setattr(journal, "read", lambda paths, since: iter(events))
    found = stats.compute(store_paths, "app", 7)
    assert found.minutes == {1: 5} and found.quota_minutes == 180


def test_cli_stats_prints_on_an_empty_store(
    store_paths: StorePaths, inside_registered_repo: Path
) -> None:
    result = runner.invoke(app, ["stats"])
    assert result.exit_code == 0
    assert "parallel: mean 0.00 workers when busy (none)" in result.stdout
