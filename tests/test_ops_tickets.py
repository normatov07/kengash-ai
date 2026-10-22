from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from super_harness.model import Doc, Folder, NeedsUser, PlanMode, Ticket, UserError
from super_harness.ops import plans, tickets
from super_harness.store import StorePaths, documents

Events = Callable[[], list[dict[str, Any]]]
BATCH = """\
- key: keyring
  title: Keyring with overlap window
  importance: critical
  touches: [services/webhooks]
  tags: [payments]
  scope: Keyring holds current and previous keys.
  acceptance: [Previous key verifies during the overlap window]
- key: rotate
  title: Rotation command
  importance: standard
  depends_on: [keyring]
"""


def plan_for(repo: Path, mode: PlanMode = PlanMode.direct, approve: bool = True) -> str:
    plan_id = plans.new_plan(
        "Rotate keys.", title="Rotatable keys", mode=mode, project=None, cwd=repo, by="x"
    ).id
    if approve:
        plans.approve_plan(plan_id, skip_review=True, project=None, by="x")
    return plan_id


def add(repo: Path, batch: str = BATCH) -> list[str]:
    added = tickets.add_tickets(plan_for(repo), batch, project=None, by="claude")
    return [new.id for new in added.tickets]


def test_add_queues_ready_and_blocked_tickets(
    store_paths: StorePaths, registered_repo: Path, run_git: Callable[..., str]
) -> None:
    plan_id = plan_for(registered_repo)
    keyring, rotate = tickets.add_tickets(plan_id, BATCH, project=None, by="claude").tickets
    assert (keyring.key, keyring.status, rotate.status) == (
        "keyring",
        "in_queue/ready",
        "in_queue/blocked",
    )
    first = tickets.show_ticket(keyring.id, project=None)
    assert (first.meta["workflow"], first.meta["loop_max"], first.meta["touches"]) == (
        "critical",
        6,
        ["services/webhooks"],
    )
    assert first.sections["Scope"] == "Keyring holds current and previous keys."
    assert first.sections["Acceptance"] == "- [ ] Previous key verifies during the overlap window"
    second = tickets.show_ticket(rotate.id, project=None).meta
    assert (second["depends_on"], second["loop_max"], second["plan"]) == ([keyring.id], 4, plan_id)
    plan = plans.show_plan(plan_id, project=None).meta
    assert (plan["status"], plan["tickets"]) == ("ticketed", [keyring.id, rotate.id])
    log = run_git(store_paths.home, "log", "--format=%s")
    assert f"harness: ticket add {keyring.id} {rotate.id}" in log


@pytest.mark.parametrize(
    ("batch", "message"),
    [
        ("{title: x}", "expected a non-empty YAML or JSON list"),
        ("[]", "expected a non-empty"),
        (
            "- {title: x, importance: simple, scop: y}",
            r"ticket 1: scop: unknown field; did you mean scope\?",
        ),
        ("- {title: x, importance: urgent}", "ticket 1: importance: "),
        ("- {title: x, importance: simple, depends_on: [nope]}", "ticket 1: unknown dependency"),
        (
            "- {key: a, title: x, importance: simple}\n- {key: a, title: y, importance: simple}",
            "keys used twice: a",
        ),
        (
            "- {key: a, title: x, importance: simple, depends_on: [b]}\n"
            "- {key: b, title: y, importance: simple, depends_on: [a]}",
            "dependency cycle: a -> b -> a",
        ),
    ],
)
def test_add_refuses_bad_batches(registered_repo: Path, batch: str, message: str) -> None:
    plan_id = plan_for(registered_repo)
    with pytest.raises(UserError, match=message):
        tickets.add_tickets(plan_id, batch, project=None, by="x")


def test_add_needs_an_approved_or_quick_plan(registered_repo: Path) -> None:
    draft = plan_for(registered_repo, approve=False)
    with pytest.raises(NeedsUser, match=f"harness plan approve {draft}"):
        tickets.add_tickets(draft, BATCH, project=None, by="x")
    quick = plan_for(registered_repo, PlanMode.quick, approve=False)
    assert len(tickets.add_tickets(quick, BATCH, project=None, by="x").tickets) == 2


def test_dependencies_on_done_tickets_are_met(
    store_paths: StorePaths, registered_repo: Path, make_ticket: Callable[..., Doc[Ticket]]
) -> None:
    documents.save_ticket(store_paths.project("payments-api"), make_ticket(status="done/merged"))
    batch = "- {title: Follow-up, importance: simple, depends_on: [7b55e0c1]}"
    added = tickets.add_tickets(plan_for(registered_repo), batch, project=None, by="x")
    assert added.tickets[0].status == "in_queue/ready"


def test_list_and_find(registered_repo: Path) -> None:
    keyring, rotate = add(registered_repo)
    lines = tickets.list_tickets(project=None, cwd=registered_repo)
    assert {(line.id, line.status, line.project) for line in lines} == {
        (keyring, "in_queue/ready", "payments-api"),
        (rotate, "in_queue/blocked", "payments-api"),
    }
    assert tickets.list_tickets(project=None, cwd=registered_repo, folder=Folder.done) == []
    assert len(tickets.list_tickets(project=None, cwd=registered_repo.parent)) == 2
    found = tickets.find_tickets("PREVIOUS keys", project=None, cwd=registered_repo)
    assert [line.id for line in found] == [keyring]
