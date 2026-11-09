"""Plan and ticket frontmatter schemas, and the document wrapper (system spec §4.4)."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from kengash_ai.model.core import Folder, Gate, Importance, ShortId, Title

PLAN_SECTIONS = (
    "Prompt",
    "Goal",
    "Decisions",
    "Lasting decisions",
    "Assumptions",
    "Scope",
    "Out of scope",
    "Design",
    "Acceptance",
    "Test seams",
    "Risks",
    "Milestones",
    "Review log",
)
TICKET_SECTIONS = (
    "Scope",
    "Acceptance",
    "Handoff",
    "Findings",
    "Decisions",
    "Check output",
    "Log",
)
_STATUS = re.compile(r"^(in_queue|in_process|done)/[a-z_]+$")

# in_process also takes the step names of SETTINGS `status.names`.
SUB_STATUSES: dict[Folder, tuple[str, ...]] = {
    Folder.in_queue: ("ready", "blocked", "parked"),
    Folder.in_process: (
        "waiting_slot",
        "waiting_paths",
        "waiting_quota",
        "needs_approval",
        "stalled",
        "failed",
        "paused",
        "awaiting_merge",
    ),
    Folder.done: ("merged", "branch_ready", "closed"),
}


class PlanMode(StrEnum):
    grill = "grill"
    direct = "direct"
    quick = "quick"


class PlanStatus(StrEnum):
    grilling = "grilling"
    draft = "draft"
    in_review = "in_review"
    approved = "approved"
    ticketed = "ticketed"
    rejected = "rejected"


class _Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class SessionRef(_Schema):
    provider: str
    model: str = "default"
    id: str


class Review(_Schema):
    round: int = 0
    max: int = 2
    verdict: Literal["pass", "fail"] | None = None
    reviewer: str | None = None
    skipped: bool = False
    session: SessionRef | None = None


class Plan(_Schema):
    id: ShortId
    uuid: UUID
    project: str
    title: Title
    mode: PlanMode
    status: PlanStatus
    review: Review = Field(default_factory=Review)
    milestone: int = 1
    tickets: list[ShortId] = Field(default_factory=list)
    created: datetime
    updated: datetime


class Ticket(_Schema):
    id: ShortId
    uuid: UUID
    project: str
    plan: ShortId
    title: Title
    importance: Importance
    workflow: str
    status: str
    step: str | None = None
    gate: Gate = Gate.afk
    loop: int = 1
    loop_max: int
    tokens: int = 0
    tokens_max: int | None = Field(None, ge=1)
    depends_on: list[ShortId] = Field(default_factory=list)
    touches: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    branch: str | None = None
    sessions: dict[str, SessionRef] = Field(default_factory=dict)
    created: datetime
    updated: datetime

    @field_validator("status")
    @classmethod
    def _status_shape(cls, value: str) -> str:
        if not _STATUS.match(value):
            raise ValueError("status must be '<in_queue|in_process|done>/<sub_status>'")
        return value

    @property
    def folder(self) -> Folder:
        return Folder(self.status.split("/", 1)[0])

    @property
    def sub_status(self) -> str:
        return self.status.split("/", 1)[1]


class TicketInput(BaseModel):
    """One item of the list `kengash ticket add` reads (SP2 spec §4)."""

    model_config = ConfigDict(extra="forbid")

    key: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]+$")] | None = None
    title: Title
    importance: Importance
    gate: Gate = Gate.afk
    touches: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    needs: dict[str, str] = Field(default_factory=dict)  # dependency → what it provides (SP18)
    provides: list[str] = Field(default_factory=list)  # exact interfaces others rely on (SP20)
    tags: list[str] = Field(default_factory=list)
    scope: str = ""
    acceptance: list[str] = Field(default_factory=list)


@dataclass
class Doc[M: BaseModel]:
    """A stored document: frontmatter model plus Markdown sections in file order."""

    meta: M
    sections: dict[str, str] = field(default_factory=dict)
