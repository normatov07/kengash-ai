from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from super_harness.model import (
    SUB_STATUSES,
    Folder,
    Gate,
    Plan,
    PlanMode,
    PlanStatus,
    Review,
    SessionRef,
    Ticket,
    TicketInput,
)

NOW = datetime(2026, 10, 22, 9, 41, tzinfo=UTC)


def ticket(**overrides: Any) -> Ticket:
    fields: dict[str, Any] = {
        "id": "7b55e0c1",
        "uuid": uuid4(),
        "project": "payments-api",
        "plan": "a1b2c3d4",
        "title": "Rotate keys",
        "importance": "critical",
        "workflow": "critical",
        "status": "in_queue/ready",
        "loop_max": 6,
        "created": NOW,
        "updated": NOW,
    }
    return Ticket.model_validate(fields | overrides)


def test_ticket_folder_comes_from_status() -> None:
    assert ticket(status="in_process/under_review").folder is Folder.in_process


@pytest.mark.parametrize("status", ["queued", "in_queue", "elsewhere/ready", "in_queue/Ready"])
def test_ticket_rejects_malformed_status(status: str) -> None:
    with pytest.raises(ValidationError, match="status must be"):
        ticket(status=status)


def test_status_is_validated_on_assignment() -> None:
    item = ticket()
    with pytest.raises(ValidationError, match="status must be"):
        item.status = "done"


def test_ticket_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ticket(colour="blue")


def test_short_ids_are_eight_lowercase_hex_digits() -> None:
    with pytest.raises(ValidationError):
        ticket(id="7B55E0C1")


def test_plan_defaults() -> None:
    plan = Plan(
        id="a1b2c3d4",
        uuid=uuid4(),
        project="payments-api",
        title="Rotatable keys",
        mode=PlanMode.grill,
        status=PlanStatus.grilling,
        created=NOW,
        updated=NOW,
    )
    assert (plan.review.round, plan.review.max, plan.tickets, plan.milestone) == (0, 2, [], 1)


def test_titles_are_one_trimmed_line() -> None:
    assert ticket(title="  Rotate keys ").title == "Rotate keys"
    with pytest.raises(ValidationError, match="must be one line"):
        ticket(title="Rotate\nkeys")


def test_sub_status_is_the_part_after_the_folder() -> None:
    item = ticket(status="in_process/needs_approval")
    assert item.sub_status == "needs_approval"
    assert item.sub_status in SUB_STATUSES[Folder.in_process]


def test_ticket_input_defaults_and_unknown_fields() -> None:
    item = TicketInput.model_validate({"title": "Keyring", "importance": "critical"})
    assert (item.key, item.gate, item.depends_on, item.scope) == (None, Gate.afk, [], "")
    with pytest.raises(ValidationError, match="scop"):
        TicketInput.model_validate({"title": "Keyring", "importance": "critical", "scop": "x"})


def test_tickets_record_their_step_and_token_budget() -> None:
    paused = ticket(status="in_process/paused", step="implement", tokens_max=300_000)
    assert (paused.sub_status, paused.step, paused.tokens_max) == ("paused", "implement", 300_000)
    assert "paused" in SUB_STATUSES[Folder.in_process]
    assert (ticket().step, ticket().tokens_max) == (None, None)
    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        ticket(tokens_max=0)


def test_plan_reviews_keep_their_reviewer_session() -> None:
    review = Review(round=1, verdict="fail", session=SessionRef(provider="codex", id="019a"))
    assert review.session == SessionRef(provider="codex", model="default", id="019a")
