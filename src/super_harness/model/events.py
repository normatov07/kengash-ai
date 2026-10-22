"""Journal events (system spec §6.1): fixed core fields plus any extra detail."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from super_harness.model.core import utc_now


class Event(BaseModel):
    model_config = ConfigDict(extra="allow")

    ts: datetime = Field(default_factory=utc_now)
    type: str
    project: str | None = None
    ticket: str | None = None
    plan: str | None = None
