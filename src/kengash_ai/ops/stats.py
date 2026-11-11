"""What a run cost and what it bought (SP20 spec §3.4), read from the journal only."""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from kengash_ai import journal
from kengash_ai.model import Event
from kengash_ai.store.paths import StorePaths

IMPLEMENTER = "implementer"
REVIEWER = "code-reviewer"


@dataclass
class ModelRow:
    """One implementing model: runs, tokens, and how often the next review passed."""

    cli: str
    runs: int = 0
    tokens: int = 0
    reviewed: int = 0
    passed: int = 0


@dataclass
class Stats:
    days: int
    minutes: dict[int, int] = field(default_factory=dict)  # workers running → minutes
    merged: int = 0
    first_pass: int = 0
    tokens: int = 0
    models: list[ModelRow] = field(default_factory=list)
    gates: dict[str, int] = field(default_factory=dict)  # cause → how many
    quota_minutes: int = 0  # steps waiting for a subscription limit, added up

    @property
    def mean_workers(self) -> float:
        """Workers running at once, averaged over the minutes any was."""
        busy = sum(self.minutes.values())
        return sum(n * m for n, m in self.minutes.items()) / busy if busy else 0.0


def report(project: str | None, days: int) -> Stats:
    """`kengash stats`: `compute` over the user's store."""
    return compute(StorePaths.default(), project, days)


def compute(paths: StorePaths, project: str | None, days: int) -> Stats:
    """The last `days` days of one project, or of every project."""
    since = date.today() - timedelta(days=days - 1)
    events = [e for e in journal.read(paths, since=since) if project in (None, e.project)]
    minutes, quota = _minutes(events)
    found = Stats(days, minutes=minutes, quota_minutes=quota)
    rows: dict[str, ModelRow] = {}
    last: dict[str, ModelRow] = {}  # ticket → the model that last implemented it
    gates: Counter[str] = Counter()
    for event in events:
        extra = event.model_extra or {}
        if event.type == "step.end":
            _count_step(found, rows, last, event, extra)
        elif event.type == "ticket.merged":
            found.merged += 1
            found.first_pass += extra.get("loop") == 1
        elif event.type == "ticket.needs_approval":
            gates[_cause(str(extra.get("reason", "")))] += 1
    found.models = sorted(rows.values(), key=lambda row: -row.tokens)
    found.gates = dict(gates.most_common())
    return found


def _count_step(
    found: Stats,
    rows: dict[str, ModelRow],
    last: dict[str, ModelRow],
    event: Event,
    extra: dict[str, object],
) -> None:
    tokens = extra.get("tokens")
    spent = int(tokens.get("in", 0)) + int(tokens.get("out", 0)) if isinstance(tokens, dict) else 0
    found.tokens += spent
    ticket = event.ticket or ""
    if extra.get("role") == IMPLEMENTER:
        cli = f"{extra.get('provider')}/{extra.get('model')}"
        row = rows.setdefault(cli, ModelRow(cli))
        row.runs += 1
        row.tokens += spent
        last[ticket] = row
    elif extra.get("role") == REVIEWER and ticket in last:
        row = last.pop(ticket)
        row.reviewed += 1
        row.passed += extra.get("verdict") == "pass"


def _cause(reason: str) -> str:
    """`loop cap`, `token cap`, `blocked`, `conflict`: the kind of gate a reason names."""
    return reason.split(":")[0].split(" in ")[0].strip() or "other"


def _minutes(events: list[Event]) -> tuple[dict[int, int], int]:
    """Minutes spent with each number of steps working, and minutes waiting for a limit. A
    step waiting for a subscription limit does no work, so it does not count as running."""
    opened: dict[tuple[str | None, object], datetime] = {}
    waiting: dict[tuple[str | None, object], datetime] = {}
    edges: list[tuple[datetime, int]] = []
    waited = 0.0
    for event in events:
        key = (event.ticket, (event.model_extra or {}).get("step"))
        if event.type == "step.start":
            opened[key] = event.ts
        elif event.type == "step.end" and key in opened:
            edges += [(opened.pop(key), 1), (event.ts, -1)]
        elif event.type == "step.quota_wait" and key in opened:
            edges += [(opened.pop(key), 1), (event.ts, -1)]
            waiting[key] = event.ts
        elif event.type == "step.quota_resume" and key in waiting:
            began = waiting.pop(key)
            waited += (event.ts - began).total_seconds()
            opened[key] = event.ts
    seconds: Counter[int] = Counter()
    running = 0
    previous: datetime | None = None
    for moment, change in sorted(edges, key=lambda edge: (edge[0], edge[1])):
        if previous is not None and running > 0:
            seconds[running] += int((moment - previous).total_seconds())
        running += change
        previous = moment
    return {count: round(total / 60) for count, total in sorted(seconds.items())}, round(
        waited / 60
    )
