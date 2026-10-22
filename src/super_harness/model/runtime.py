"""Engine bookkeeping files under runtime/ (SP3 spec §4); never versioned."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from super_harness.model.core import utc_now


class _Runtime(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SlotEntry(_Runtime):
    """A provider session one step holds, or waits for."""

    provider: str
    project: str
    ticket: str
    step: str
    pid: int
    since: datetime = Field(default_factory=utc_now)


class SlotTable(_Runtime):
    """runtime/slots.json: held slots, and waiting steps in arrival order."""

    held: list[SlotEntry] = Field(default_factory=list)
    waiting: list[SlotEntry] = Field(default_factory=list)


class Claims(_Runtime):
    """runtime/claims.json: when each project last had a ticket claimed."""

    last: dict[str, datetime] = Field(default_factory=dict)
