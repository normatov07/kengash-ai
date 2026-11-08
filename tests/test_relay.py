"""A finishing worker starts what is runnable (SP17 spec §3.4)."""

import argparse
from collections.abc import Callable
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import write_settings
from typer.testing import CliRunner

from kengash_ai.cli import app
from kengash_ai.model import Doc, RelayIntent, Ticket, UserError, utc_now
from kengash_ai.ops import controls, leases, loops, queue, relay, steps, watch
from kengash_ai.ops.queue import NextTicket, Queue
from kengash_ai.store import StorePaths, documents, runtime


def _ready(ticket: str = "aaaa1111", project: str = "payments-api") -> NextTicket:
    return NextTicket(ticket, project, "standard", "plan", "claude", "t")


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake(ids: list[str], **_: Any) -> controls.RunResult:
        calls.append(list(ids))
        return controls.RunResult(
            started=[controls.Started(i, "payments-api", "plan", "claude") for i in ids]
        )

    monkeypatch.setattr(controls, "run_tickets", fake)
    return calls


def _queue(monkeypatch: pytest.MonkeyPatch, **fields: Any) -> None:
    monkeypatch.setattr(queue, "compute", lambda paths, project: Queue(**fields))


def test_without_a_loop_nothing_starts(
    store_paths: StorePaths,
    registered_repo: Any,
    started: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _queue(monkeypatch, runnable=[_ready()])
    assert relay.advance(store_paths) == []
    assert started == []


def test_a_claim_lets_runnable_tickets_start(
    store_paths: StorePaths,
    registered_repo: Any,
    started: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relay.note_claim(store_paths, None)
    _queue(monkeypatch, runnable=[_ready()], running=1)
    assert relay.advance(store_paths) == ["aaaa1111"]
    assert started == [["aaaa1111"]]


def test_loop_relay_false_keeps_a_project_out(
    store_paths: StorePaths,
    registered_repo: Any,
    started: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_settings(store_paths, "loop_relay: false\n")
    relay.note_claim(store_paths, None)
    _queue(monkeypatch, runnable=[_ready()], running=1)
    assert relay.advance(store_paths) == []


def test_a_paused_project_starts_nothing(
    store_paths: StorePaths,
    registered_repo: Any,
    make_ticket: Callable[..., Doc[Ticket]],
    started: list[list[str]],
) -> None:
    documents.save_ticket(store_paths.project("payments-api"), make_ticket("aaaa1111"))
    relay.note_claim(store_paths, None)
    runtime.set_pause(store_paths, "payments-api", on=True)
    assert relay.advance(store_paths) == []
    assert started == []


def test_the_intent_ends_when_nothing_is_left(
    store_paths: StorePaths,
    registered_repo: Any,
    started: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relay.note_claim(store_paths, None)
    _queue(monkeypatch)
    relay.advance(store_paths)
    assert runtime.load_relay(store_paths).scopes == []


@pytest.mark.parametrize(
    "fields",
    [
        {"gates": 1},
        {"running": 1},
        {"held_back": {"a": "no slot"}},
        {"paused": 2},
        {"blocked": 3},
    ],
)
def test_the_intent_stays_while_something_can_still_move(
    store_paths: StorePaths,
    registered_repo: Any,
    started: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
    fields: dict[str, Any],
) -> None:
    relay.note_claim(store_paths, None)
    _queue(monkeypatch, **fields)
    relay.advance(store_paths)
    assert runtime.load_relay(store_paths).scopes == ["all"]


def test_a_failure_never_escapes(
    store_paths: StorePaths, registered_repo: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    relay.note_claim(store_paths, None)

    def boom(paths: StorePaths, project: str | None) -> Queue:
        raise RuntimeError("no")

    monkeypatch.setattr(queue, "compute", boom)
    assert relay.advance_quietly(store_paths) == []


def test_a_release_clears_the_scope(store_paths: StorePaths, registered_repo: Any) -> None:
    relay.note_claim(store_paths, "payments-api")
    relay.note_claim(store_paths, None)
    relay.note_release(store_paths, "payments-api")
    assert runtime.load_relay(store_paths).scopes == ["all"]


def test_loop_claim_and_release_record_the_intent(
    store_paths: StorePaths, registered_repo: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(watch, "open_dashboard", lambda paths, project: "")
    loops.claim(None)
    assert runtime.load_relay(store_paths).scopes == ["all"]
    loops.release(force=True)
    assert runtime.load_relay(store_paths).scopes == []


def test_an_unexpected_failure_never_escapes(
    store_paths: StorePaths, registered_repo: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    relay.note_claim(store_paths, None)

    def boom(paths: StorePaths, project: str | None) -> Queue:
        raise ValueError("a bug in the relay must not fail a ticket that passed")

    monkeypatch.setattr(queue, "compute", boom)
    assert relay.advance_quietly(store_paths) == []


def test_an_intent_left_idle_is_forgotten(
    store_paths: StorePaths,
    registered_repo: Any,
    started: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = RelayIntent(scopes=["all"], touched=utc_now() - relay.MAX_IDLE - timedelta(minutes=1))
    runtime.save_relay(store_paths, old)
    _queue(monkeypatch, runnable=[_ready()])
    assert relay.advance(store_paths) == []
    assert started == []
    assert runtime.load_relay(store_paths).scopes == []


def test_starting_a_ticket_keeps_the_intent_fresh(
    store_paths: StorePaths,
    registered_repo: Any,
    started: list[list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = utc_now() - timedelta(hours=1)
    runtime.save_relay(store_paths, RelayIntent(scopes=["all"], touched=before))
    _queue(monkeypatch, runnable=[_ready()])
    assert relay.advance(store_paths) == ["aaaa1111"]
    assert runtime.load_relay(store_paths).touched > before


def test_a_release_without_a_lease_forgets_the_scopes_no_lease_covers(
    store_paths: StorePaths, registered_repo: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime.save_relay(store_paths, RelayIntent(scopes=["all", "payments-api"]))
    held = SimpleNamespace(project="payments-api")
    monkeypatch.setattr(leases, "live", lambda paths: [held])
    assert loops.release().scope is None
    assert runtime.load_relay(store_paths).scopes == ["payments-api"]


def test_loop_status_says_what_the_relay_still_covers(
    store_paths: StorePaths, registered_repo: Any
) -> None:
    relay.note_claim(store_paths, None)
    assert "relay on: all" in CliRunner().invoke(app, ["loop", "status"]).output


def _bad_settings(paths: StorePaths, project: str | None) -> Queue:
    raise UserError("settings: bad value")


def test_a_settings_error_keeps_the_loop(
    store_paths: StorePaths, registered_repo: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    relay.note_claim(store_paths, "payments-api")
    monkeypatch.setattr(queue, "compute", _bad_settings)
    assert relay.advance(store_paths) == []
    assert runtime.load_relay(store_paths).scopes == ["payments-api"]


def test_a_removed_project_is_forgotten(
    store_paths: StorePaths, registered_repo: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    relay.note_claim(store_paths, "gone")
    monkeypatch.setattr(queue, "compute", _bad_settings)
    relay.advance(store_paths)
    assert runtime.load_relay(store_paths).scopes == []


def _noting(order: list[str], name: str, value: object = None) -> Callable[..., Any]:
    def note(*_: object, **__: object) -> Any:
        order.append(name)
        return value

    return note


@pytest.fixture
def relayed(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    order: list[str] = []
    monkeypatch.setattr(relay, "advance_quietly", _noting(order, "relayed", []))
    return order


def test_an_approval_can_start_the_next_tickets(
    registered_repo: Any, relayed: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def approved(*_: Any, **__: Any) -> controls.Approved:
        relayed.append("approved")
        return controls.Approved("aaaa1111", "payments-api", "done/merged", "")

    monkeypatch.setattr(controls, "approve_ticket", approved)
    assert CliRunner().invoke(app, ["approve", "aaaa1111"]).exit_code == 0
    assert relayed == ["approved", "relayed"]


def test_a_resume_can_start_the_next_tickets(
    registered_repo: Any, relayed: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def resumed(*_: Any, **__: Any) -> controls.Resumed:
        relayed.append("resumed")
        return controls.Resumed([])

    monkeypatch.setattr(controls, "resume", resumed)
    assert CliRunner().invoke(app, ["resume"]).exit_code == 0
    assert relayed == ["resumed", "relayed"]


def test_a_worker_that_fails_still_starts_the_next_tickets(
    relayed: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from kengash_ai.worker.__main__ import _job

    monkeypatch.setattr(steps, "fail_job", lambda *_, **__: relayed.append("failed"))
    args = argparse.Namespace(job="ticket", id="aaaa1111", project=None, steps=None)
    _, _, fail = _job(args)
    fail("worker error")
    assert relayed == ["failed", "relayed"]
