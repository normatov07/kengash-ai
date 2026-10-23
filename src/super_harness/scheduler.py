"""Which ready tickets may start now: overlap, slots and project turns (SP3 spec §7).

Pure: callers pass tickets, running work and limits in, and get a selection back.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import zip_longest
from typing import NamedTuple

from super_harness.model import Importance

RANK = {Importance.critical: 0, Importance.standard: 1, Importance.simple: 2}
NEVER = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True)
class Candidate:
    """A ready ticket; `provider` is the CLI its first step needs (None: no slot)."""

    id: str
    project: str
    importance: Importance
    created: datetime
    touches: tuple[str, ...]
    provider: str | None


@dataclass(frozen=True)
class Busy:
    """An in_process ticket: it keeps its paths until it leaves in_process."""

    id: str
    project: str
    touches: tuple[str, ...]


class Held(NamedTuple):
    """A provider session that a running step holds."""

    project: str
    provider: str


@dataclass(frozen=True)
class Limits:
    """`sessions.max` and `sessions.per_provider` of one settings scope."""

    total: int
    per_provider: Mapping[str, int]


@dataclass
class Selection:
    chosen: list[Candidate] = field(default_factory=list)
    held_back: dict[str, str] = field(default_factory=dict)


def overlaps(a: Sequence[str], b: Sequence[str]) -> bool:
    """Path prefixes overlap when one contains the other, segment by segment; an empty
    list stands for the whole repo."""
    if not a or not b:
        return True
    return any(_within(x, y) or _within(y, x) for x in a for y in b)


def select(
    candidates: Sequence[Candidate],
    busy: Sequence[Busy],
    held: Sequence[Held],
    machine: Limits,
    projects: Mapping[str, Limits],
    last_claims: Mapping[str, datetime],
) -> Selection:
    """Walk candidates in turn order; keep each one that overlaps nothing running or chosen
    in its project and fits a free slot on this machine and in its project."""
    selection = Selection()
    taken = list(busy)
    used = list(held)
    for candidate in _in_turns(candidates, last_claims):
        clash = next(
            (
                other.id
                for other in taken
                if other.project == candidate.project and overlaps(other.touches, candidate.touches)
            ),
            None,
        )
        if clash is not None:
            selection.held_back[candidate.id] = f"touches overlap {clash}"
            continue
        provider = candidate.provider
        if provider is not None:
            if not fits(provider, candidate.project, used, machine, projects):
                selection.held_back[candidate.id] = f"no free {provider} slot"
                continue
            used.append(Held(candidate.project, provider))
        selection.chosen.append(candidate)
        taken.append(Busy(candidate.id, candidate.project, candidate.touches))
    return selection


def fits(
    provider: str,
    project: str,
    used: Sequence[Held],
    machine: Limits,
    projects: Mapping[str, Limits],
) -> bool:
    """One more `provider` session for `project` stays within the machine's and the
    project's limits, given the sessions in `used`."""
    own = [slot for slot in used if slot.project == project]
    limits = projects.get(project, machine)
    return _fits(provider, used, machine) and _fits(provider, own, limits)


def _fits(provider: str, used: Sequence[Held], limits: Limits) -> bool:
    same = sum(slot.provider == provider for slot in used)
    return len(used) < limits.total and same < limits.per_provider.get(provider, 0)


def _in_turns(
    candidates: Sequence[Candidate], last_claims: Mapping[str, datetime]
) -> list[Candidate]:
    """Projects take turns, the one with the oldest last claim first; inside a project,
    critical before standard before simple, then oldest first."""
    queues: dict[str, list[Candidate]] = {}
    for candidate in sorted(candidates, key=lambda c: (RANK[c.importance], c.created, c.id)):
        queues.setdefault(candidate.project, []).append(candidate)
    order = sorted(queues, key=lambda slug: (last_claims.get(slug, NEVER), slug))
    turns = zip_longest(*(queues[slug] for slug in order))
    return [candidate for turn in turns for candidate in turn if candidate is not None]


def _segments(path: str) -> list[str]:
    return [part for part in path.strip().split("/") if part not in ("", ".")]


def _within(inner: str, outer: str) -> bool:
    """True when `inner` lies inside `outer`, or is it."""
    prefix = _segments(outer)
    return _segments(inner)[: len(prefix)] == prefix
