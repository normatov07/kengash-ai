"""Schemas and errors shared by every unit; no I/O and no harness imports."""

from super_harness.model.core import Folder, Gate, Importance, ShortId, utc_now
from super_harness.model.documents import (
    PLAN_SECTIONS,
    TICKET_SECTIONS,
    Doc,
    Plan,
    PlanMode,
    PlanStatus,
    Review,
    SessionRef,
    Ticket,
)
from super_harness.model.errors import HarnessError, NeedsSetup, NeedsUser, UserError
from super_harness.model.registry import ProjectEntry, Registry

__all__ = [
    "PLAN_SECTIONS",
    "TICKET_SECTIONS",
    "Doc",
    "Folder",
    "Gate",
    "HarnessError",
    "Importance",
    "NeedsSetup",
    "NeedsUser",
    "Plan",
    "PlanMode",
    "PlanStatus",
    "ProjectEntry",
    "Registry",
    "Review",
    "SessionRef",
    "ShortId",
    "Ticket",
    "UserError",
    "utc_now",
]
