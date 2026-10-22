"""Primitive types shared by every schema."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import StringConstraints

ShortId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{8}$")]


class Importance(StrEnum):
    simple = "simple"
    standard = "standard"
    critical = "critical"


class Gate(StrEnum):
    afk = "afk"
    hitl = "hitl"


class Folder(StrEnum):
    in_queue = "in_queue"
    in_process = "in_process"
    done = "done"


def utc_now() -> datetime:
    """Current UTC time at second precision, as stored in frontmatter."""
    return datetime.now(UTC).replace(microsecond=0)
