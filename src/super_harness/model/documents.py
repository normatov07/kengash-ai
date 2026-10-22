"""Plan and ticket frontmatter schemas, and the document wrapper (system spec §4.4)."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from super_harness.model.core import Folder, Gate, Importance, ShortId

PLAN_SECTIONS = (
    "Prompt",
    "Goal",
    "Decisions",
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
TICKET_SECTIONS = ("Scope", "Acceptance", "Handoff", "Findings", "Log")
_STATUS = re.compile(r"^(in_queue|in_process|done)/[a-z_]+$")


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


class Review(_Schema):
    round: int = 0
    max: int = 2
    verdict: Literal["pass", "fail"] | None = None
    reviewer: str | None = None
    skipped: bool = False


class Plan(_Schema):
    id: ShortId
    uuid: UUID
    project: str
    title: str
    mode: PlanMode
    status: PlanStatus
    review: Review = Field(default_factory=Review)
    milestone: int = 1
    tickets: list[ShortId] = Field(default_factory=list)
    created: datetime
    updated: datetime


class SessionRef(_Schema):
    provider: str
    model: str = "default"
    id: str


class Ticket(_Schema):
    id: ShortId
    uuid: UUID
    project: str
    plan: ShortId
    title: str
    importance: Importance
    workflow: str
    status: str
    gate: Gate = Gate.afk
    loop: int = 1
    loop_max: int
    tokens: int = 0
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


@dataclass
class Doc[M: BaseModel]:
    """A stored document: frontmatter model plus Markdown sections in file order."""

    meta: M
    sections: dict[str, str] = field(default_factory=dict)
