"""Journal events (system spec §6.1): fixed core fields plus any extra detail."""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from super_harness.model.core import utc_now


class Event(BaseModel):
    model_config = ConfigDict(extra="allow")

    ts: datetime = Field(default_factory=utc_now)
    type: str
    project: str | None = None
    ticket: str | None = None
    plan: str | None = None

    @field_validator("ts")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        """Keep times in UTC, so the journal file's day and the `Z` suffix always hold."""
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
