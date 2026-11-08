"""kengash loop claim, release and status (SP11 spec §4.8)."""

import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kengash_ai import journal
from kengash_ai.cli import app
from kengash_ai.model import Doc, Event, PlanMode, SlotEntry, SlotTable, Ticket
from kengash_ai.ops import conductors, plans, tickets
from kengash_ai.ops.conductors import Conductor, process_name
from kengash_ai.store import StorePaths, documents, runtime

runner = CliRunner()
ME = Conductor(os.getpid(), "claude", process_name(os.getpid()) or "", True)
OTHER = Conductor(os.getppid(), "codex", process_name(os.getppid()) or "", True)
As = Callable[[Conductor], None]


@pytest.fixture
def as_conductor(monkeypatch: pytest.MonkeyPatch) -> As:
    def use(who: Conductor) -> None:
        monkeypatch.setattr(conductors, "conductor", lambda: who)

    return use


@pytest.mark.usefixtures("inside_registered_repo")
def test_claim_prints_and_a_second_conductor_exits_6(as_conductor: As) -> None:
    as_conductor(OTHER)
    first = runner.invoke(app, ["loop", "claim"])
    assert (first.exit_code, first.stdout) == (
        0,
        "loop claimed: all projects (watch: kengash watch)\n",
    )
    as_conductor(ME)
    second = runner.invoke(app, ["loop", "claim", "-p", "payments-api"])
    assert second.exit_code == 6
    assert second.stderr == (
        f"loop running: codex pid {OTHER.pid} on all projects, seen just now"
        "; if that loop has ended: kengash loop claim --take-over\n"
    )


@pytest.mark.usefixtures("inside_registered_repo")
def test_take_over_flag(as_conductor: As) -> None:
    as_conductor(OTHER)
    runner.invoke(app, ["loop", "claim", "-p", "payments-api"])
    as_conductor(ME)
    taken = runner.invoke(app, ["loop", "claim", "-p", "payments-api", "--take-over"])
    assert (taken.exit_code, taken.stdout) == (
        0,
        "loop claimed: payments-api (watch: kengash watch -p payments-api)\n",
    )
    as_conductor(OTHER)
    assert runner.invoke(app, ["loop", "claim", "-p", "payments-api"]).exit_code == 6


@pytest.mark.usefixtures("inside_registered_repo")
def test_release_refuses_while_runnable_then_force_releases(
    as_conductor: As, store_paths: StorePaths, make_ticket: Callable[..., Doc[Ticket]]
) -> None:
    as_conductor(ME)
    runner.invoke(app, ["loop", "claim", "-p", "payments-api"])
    documents.save_ticket(store_paths.project("payments-api"), make_ticket())
    refused = runner.invoke(app, ["loop", "release"])
    assert refused.exit_code == 1
    assert refused.stderr == "not released: 1 runnable; run: kengash next\n"
    forced = runner.invoke(app, ["loop", "release", "--force"])
    assert (forced.exit_code, forced.stdout) == (0, "loop released: payments-api\n")
    as_conductor(OTHER)
    assert runner.invoke(app, ["loop", "claim", "-p", "payments-api"]).exit_code == 0


@pytest.mark.usefixtures("inside_registered_repo")
def test_release_without_a_lease(as_conductor: As) -> None:
    as_conductor(ME)
    result = runner.invoke(app, ["loop", "release"])
    assert (result.exit_code, result.stdout) == (0, "no loop held here\n")


@pytest.mark.usefixtures("inside_registered_repo")
def test_status_lines(as_conductor: As, store_paths: StorePaths) -> None:
    as_conductor(ME)
    assert runner.invoke(app, ["loop", "status"]).stdout == "no loop running\nloop_start: ask\n"
    runner.invoke(app, ["loop", "claim", "-p", "payments-api"])
    mine = runner.invoke(app, ["loop", "status", "-p", "payments-api"]).stdout
    assert mine == (
        "this session holds the loop on payments-api\nloop_start: ask\nrelay on: payments-api\n"
    )
    settings = store_paths.project("payments-api").settings
    text = settings.read_text().replace("loop_start: ask", "loop_start: auto")
    settings.write_text(text, encoding="utf-8")
    as_conductor(OTHER)
    seen = runner.invoke(app, ["loop", "status", "-p", "payments-api"]).stdout
    assert seen == (
        f"loop running: claude pid {ME.pid} on payments-api, seen just now\nloop_start: auto\n"
        "relay on: payments-api\n"
    )


@pytest.mark.usefixtures("inside_registered_repo")
def test_status_json(as_conductor: As) -> None:
    as_conductor(ME)
    runner.invoke(app, ["loop", "claim"])
    data = json.loads(runner.invoke(app, ["loop", "status", "--json"]).stdout)
    assert data["loop_start"] == "ask"
    (lease,) = data["leases"]
    assert (lease["pid"], lease["mine"], lease["scope"], lease["project"]) == (
        ME.pid,
        True,
        "all projects",
        None,
    )


def test_status_outside_a_store_is_empty(as_conductor: As, tmp_path: Path) -> None:
    as_conductor(ME)
    result = runner.invoke(app, ["loop", "status"])
    assert (result.exit_code, result.stdout) == (0, "no loop running\nloop_start: ask\n")


@pytest.mark.usefixtures("inside_registered_repo")
def test_wait_refuses_under_another_conductors_lease(as_conductor: As) -> None:
    as_conductor(OTHER)
    runner.invoke(app, ["loop", "claim"])
    as_conductor(ME)
    refused = runner.invoke(app, ["wait", "--timeout", "0.1"])
    assert refused.exit_code == 6
    assert refused.stderr.startswith(f"loop running: codex pid {OTHER.pid} on all projects")
    undetected = Conductor(ME.pid, "unknown", ME.command, False)
    as_conductor(undetected)
    assert runner.invoke(app, ["wait", "--timeout", "0.1"]).exit_code == 6


def _gate(ticket_id: str) -> Event:
    return Event.model_validate(
        {
            "type": "ticket.awaiting_merge",
            "project": "payments-api",
            "ticket": ticket_id,
            "status": "awaiting_merge",
            "loop": 1,
            "loop_max": 3,
            "reason": "every step passed",
        }
    )


@pytest.mark.usefixtures("inside_registered_repo")
def test_wait_folds_queued_lines_and_keeps_gates(
    as_conductor: As, store_paths: StorePaths, inside_registered_repo: Path
) -> None:
    as_conductor(ME)
    runner.invoke(app, ["wait", "--timeout", "0.1"])  # sets the cursor
    plan_id = plans.new_plan(
        "Six.", title="Six", mode=PlanMode.quick, project=None, cwd=inside_registered_repo, by="x"
    ).id
    batch = "".join(
        f"- title: Slice {n}\n  importance: simple\n  touches: [s{n}]\n  scope: S.\n"
        "  acceptance: [ok]\n"
        for n in range(6)
    )
    tickets.add_tickets(plan_id, batch, project=None, by="x")
    journal.append(store_paths, _gate("aaaaaaa1"))
    lines = runner.invoke(app, ["wait", "--timeout", "0.1"]).stdout.splitlines()
    assert lines == [
        "aaaaaaa1 awaiting_merge loop 1/3: every step passed",
        "queued: 6 tickets ready; run: kengash next",
    ]


@pytest.mark.usefixtures("inside_registered_repo")
def test_capped_wait_points_at_status(as_conductor: As, store_paths: StorePaths) -> None:
    as_conductor(ME)
    runner.invoke(app, ["wait", "--timeout", "0.1"])
    for n in range(6):
        journal.append(store_paths, _gate(f"aaaaaaa{n}"))
    lines = runner.invoke(app, ["wait", "--timeout", "0.1"]).stdout.splitlines()
    assert len(lines) == 5 and lines[-1] == "+2 more; run: kengash status"


@pytest.mark.usefixtures("inside_registered_repo")
def test_release_refuses_while_ready_tickets_wait_for_a_slot(
    as_conductor: As, store_paths: StorePaths, make_ticket: Callable[..., Doc[Ticket]]
) -> None:
    as_conductor(ME)
    runner.invoke(app, ["loop", "claim", "-p", "payments-api"])
    documents.save_ticket(store_paths.project("payments-api"), make_ticket())
    held = [
        SlotEntry(provider="claude", project="other", ticket=f"b{n}", step="plan", pid=os.getpid())
        for n in range(3)
    ]
    runtime.save_slots(store_paths, SlotTable(held=held))
    refused = runner.invoke(app, ["loop", "release"])
    assert refused.exit_code == 1
    assert refused.stderr == "not released: 1 ready, waiting for a slot; run: kengash wait\n"
    runtime.save_slots(store_paths, SlotTable())
    assert runner.invoke(app, ["loop", "release"]).stderr.startswith("not released: 1 runnable")
