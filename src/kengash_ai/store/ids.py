"""Plan and ticket ids: uuid4, with its first 8 hex digits as the short id."""

import re
from collections.abc import Container
from uuid import UUID, uuid4

# 12345678 and 1234e567 load from unquoted YAML as numbers, so agents could not list them.
_NUMBER = re.compile(r"[0-9]+(e[0-9]+)?")


def new_id(taken: Container[str]) -> tuple[str, UUID]:
    """Return a fresh (short id, uuid), re-rolling while the short id is taken or numeric."""
    for _ in range(64):
        value = uuid4()
        short = value.hex[:8]
        if short not in taken and not _NUMBER.fullmatch(short):
            return short, value
    raise RuntimeError("no free short id after 64 attempts")
