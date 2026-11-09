"""Which ready tickets may start now: overlap, slots and project turns (SP3 spec §7).

Pure: callers pass tickets, running work and limits in, and get a selection back.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from fnmatch import fnmatch
from itertools import zip_longest
from math import ceil
from typing import NamedTuple

from kengash_ai.model import Importance

RANK = {Importance.critical: 0, Importance.standard: 1, Importance.simple: 2}
NEVER = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True)
class Candidate:
    """A ready ticket; `provider` is the CLI its first step needs (None: no slot). `editing`:
    that step is in the editing phase, so its paths matter; `weight`: its longest chain of
    waiting dependents (SP16 spec §3.7, §3.13)."""

    id: str
    project: str
    importance: Importance
    created: datetime
    touches: tuple[str, ...]
    provider: str | None
    editing: bool = True
    weight: int = 0


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
class PathPolicy:
    """What two editing tickets may share (SP17 spec §3.5): files matching `shared` are never
    claimed, and up to `max_overlap` exact files may overlap. The default is strict."""

    shared: tuple[str, ...] = ()
    max_overlap: int = 0


@dataclass(frozen=True)
class Limits:
    """`sessions.max` and `sessions.per_provider` of one settings scope, and its path policy."""

    total: int
    per_provider: Mapping[str, int]
    paths: PathPolicy = PathPolicy()


@dataclass
class Selection:
    chosen: list[Candidate] = field(default_factory=list)
    held_back: dict[str, str] = field(default_factory=dict)


def clash(a: Sequence[str], b: Sequence[str], policy: PathPolicy) -> bool:
    """True when tickets touching `a` and `b` may not edit at once: an empty list is the whole
    repo, a directory clashes with whatever it holds, and exact files may overlap up to
    `policy.max_overlap`; generated files (`policy.shared`) do not count."""
    if not a or not b:
        return True
    shared_files = 0
    for x, y in ((x, y) for x in a for y in b):
        if not (_within(x, y) or _within(y, x)):
            continue
        if _shared(x, policy) or _shared(y, policy):
            continue
        if _is_directory(x) or _is_directory(y):
            return True
        shared_files += 1
    return shared_files > policy.max_overlap


def select(
    candidates: Sequence[Candidate],
    busy: Sequence[Busy],
    held: Sequence[Held],
    machine: Limits,
    projects: Mapping[str, Limits],
    last_claims: Mapping[str, datetime],
) -> Selection:
    """Walk candidates in turn order; keep each one that fits a free slot on this machine and
    in its project and, when it starts editing, overlaps no path holder in `busy` or editor
    already chosen. A candidate that starts by planning edits nothing, so paths do not matter."""
    selection = Selection()
    taken = list(busy)
    used = list(held)
    for candidate in _in_turns(candidates, last_claims):
        holder = (
            next(
                (
                    other.id
                    for other in taken
                    if other.project == candidate.project
                    and clash(
                        other.touches,
                        candidate.touches,
                        projects.get(candidate.project, machine).paths,
                    )
                ),
                None,
            )
            if candidate.editing
            else None
        )
        if holder is not None:
            selection.held_back[candidate.id] = f"touches overlap {holder}"
            continue
        provider = candidate.provider
        if provider is not None:
            if not fits(provider, candidate.project, used, machine, projects):
                selection.held_back[candidate.id] = f"no free {provider} slot"
                continue
            used.append(Held(candidate.project, provider))
        selection.chosen.append(candidate)
        if candidate.editing:
            taken.append(Busy(candidate.id, candidate.project, candidate.touches))
    return selection


@dataclass(frozen=True)
class Shape:
    """A ticket graph (SP18 spec §3.6): how many, in how many levels, how many at once at the
    widest; `chokepoints` holds (ticket, tickets behind it), most first."""

    tickets: int
    levels: int
    widest: int
    chokepoints: tuple[tuple[str, int], ...] = ()


def behind(depends: Mapping[str, Sequence[str]]) -> dict[str, set[str]]:
    """Each ticket's transitive dependents; an edge to a ticket not listed is ignored."""
    dependents: dict[str, list[str]] = {ticket: [] for ticket in depends}
    for ticket, needs in depends.items():
        for need in needs:
            if need in dependents:
                dependents[need].append(ticket)
    found: dict[str, set[str]] = {}
    for ticket in depends:
        seen: set[str] = set()
        stack = list(dependents[ticket])
        while stack:
            current = stack.pop()
            if current not in seen and current != ticket:
                seen.add(current)
                stack.extend(dependents[current])
        found[ticket] = seen
    return found


def shape(depends: Mapping[str, Sequence[str]]) -> Shape:
    """The graph's levels and chokepoints: a ticket past the first level holding at least
    max(3, a quarter of the graph) behind it. A first-level ticket is the shared foundation
    the width guidance asks for, so it never counts."""
    level = _levels(depends)
    if not level:
        return Shape(0, 0, 0)
    per_level = Counter(level.values())
    bar = max(3, ceil(len(depends) / 4))
    held = behind(depends)
    points = sorted(
        ((t, len(held[t])) for t in depends if level[t] > 0 and len(held[t]) >= bar),
        key=lambda point: (-point[1], point[0]),
    )
    return Shape(len(depends), len(per_level), max(per_level.values()), tuple(points))


def _levels(depends: Mapping[str, Sequence[str]]) -> dict[str, int]:
    """Each ticket's longest chain of tickets before it; a cycle counts as no chain."""
    found: dict[str, int] = {}
    visiting: set[str] = set()

    def level(ticket: str) -> int:
        if ticket in found:
            return found[ticket]
        if ticket in visiting:
            return 0
        visiting.add(ticket)
        needs = [need for need in depends[ticket] if need in depends]
        value = max((1 + level(need) for need in needs), default=0)
        visiting.discard(ticket)
        found[ticket] = value
        return value

    return {ticket: level(ticket) for ticket in depends}


def shared_paths(a: Sequence[str], b: Sequence[str], policy: PathPolicy) -> list[str]:
    """The claimed paths that make `a` and `b` overlap, generated files left out."""
    found = [
        x
        for x in a
        for y in b
        if (_within(x, y) or _within(y, x)) and not (_shared(x, policy) or _shared(y, policy))
    ]
    return list(dict.fromkeys(found))


def is_broad(path: str, policy: PathPolicy) -> bool:
    """A whole top-level folder, which keeps most other tickets waiting."""
    return len(_segments(path)) <= 1 and _is_directory(path) and not _shared(path, policy)


def needs_claim(path: str, touches: Sequence[str], policy: PathPolicy) -> bool:
    """`path` is outside every claim in `touches` and is not a generated file."""
    return not _shared(path, policy) and not any(_within(path, claim) for claim in touches)


def chain_weights(depends: Mapping[str, Sequence[str]]) -> dict[str, int]:
    """Each ticket's longest chain of tickets waiting on it, transitively (0: none). Starting
    the longest chain first shortens the whole run (Hu's rule); a cycle counts as no chain."""
    dependents: dict[str, list[str]] = {ticket: [] for ticket in depends}
    for ticket, needs in depends.items():
        for need in needs:
            dependents.setdefault(need, []).append(ticket)
    weights: dict[str, int] = {}
    visiting: set[str] = set()

    def weight(ticket: str) -> int:
        if ticket in weights:
            return weights[ticket]
        if ticket in visiting:
            return 0
        visiting.add(ticket)
        found = max((1 + weight(child) for child in dependents.get(ticket, [])), default=0)
        visiting.discard(ticket)
        weights[ticket] = found
        return found

    return {ticket: weight(ticket) for ticket in depends}


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
    """Projects take turns, the one with the oldest last claim first; inside a project, the
    longest chain of waiting dependents first, then critical before standard before simple,
    then oldest first."""
    queues: dict[str, list[Candidate]] = {}
    ranked = sorted(candidates, key=lambda c: (-c.weight, RANK[c.importance], c.created, c.id))
    for candidate in ranked:
        queues.setdefault(candidate.project, []).append(candidate)
    order = sorted(queues, key=lambda slug: (last_claims.get(slug, NEVER), slug))
    turns = zip_longest(*(queues[slug] for slug in order))
    return [candidate for turn in turns for candidate in turn if candidate is not None]


def _shared(path: str, policy: PathPolicy) -> bool:
    return any(fnmatch(path.strip(), pattern) for pattern in policy.shared)


def _is_directory(path: str) -> bool:
    """A trailing slash, or a last segment with no extension."""
    parts = _segments(path)
    return path.strip().endswith("/") or not parts or "." not in parts[-1]


def _segments(path: str) -> list[str]:
    return [part for part in path.strip().split("/") if part not in ("", ".")]


def _within(inner: str, outer: str) -> bool:
    """True when `inner` lies inside `outer`, or is it."""
    prefix = _segments(outer)
    return _segments(inner)[: len(prefix)] == prefix
