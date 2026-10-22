"""Plan and ticket ids: uuid4, with its first 8 hex digits as the short id."""

from collections.abc import Container
from uuid import UUID, uuid4


def new_id(taken: Container[str]) -> tuple[str, UUID]:
    """Return a fresh (short id, uuid), re-rolling while the short id is taken."""
    for _ in range(64):
        value = uuid4()
        if value.hex[:8] not in taken:
            return value.hex[:8], value
    raise RuntimeError("no free short id after 64 attempts")
