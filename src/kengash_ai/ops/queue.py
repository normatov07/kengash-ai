"""What can start now: ready tickets that pass the scheduler's rules (SP3 spec §7)."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from kengash_ai import scheduler, settings, workflow
from kengash_ai.model import Doc, Folder, Gate, Settings, Ticket, split_cli
from kengash_ai.ops import lifecycle, records, waiting
from kengash_ai.ops.workspace import GATES
from kengash_ai.store import runtime
from kengash_ai.store.paths import StorePaths

NO_SLOT = ("shell", "user")  # run_tests steps and the user's approval need no session
STUCK_MIN = 3


@dataclass
class NextTicket:
    id: str
    project: str
    importance: str
    step: str
    provider: str
    title: str


@dataclass(frozen=True)
class Stuck:
    """A ticket at a gate or parked with many unfinished tickets behind it (SP18 spec §3.8)."""

    id: str
    project: str
    status: str
    behind: int


@dataclass
class Queue:
    runnable: list[NextTicket] = field(default_factory=list)
    held_back: dict[str, str] = field(default_factory=dict)
    blocked: int = 0
    running: int = 0
    gates: int = 0
    paused: int = 0
    stuck: list[Stuck] = field(default_factory=list)


def stuck(docs: Mapping[str, Doc[Ticket]], slug: str) -> list[Stuck]:
    """Tickets that need someone and hold at least STUCK_MIN others back, most first."""
    unfinished = {key: doc.meta for key, doc in docs.items() if doc.meta.folder is not Folder.done}
    graph = {key: list(meta.depends_on) for key, meta in unfinished.items()}
    waiting = scheduler.behind(graph)
    found = [
        Stuck(key, slug, meta.status, len(waiting[key]))
        for key, meta in unfinished.items()
        if len(waiting[key]) >= STUCK_MIN and _needs_someone(meta)
    ]
    return sorted(found, key=lambda item: (-item.behind, item.id))


def _needs_someone(ticket: Ticket) -> bool:
    if ticket.folder is Folder.in_process:
        return ticket.sub_status in GATES
    return ticket.status == "in_queue/parked"


def next_tickets(project: str | None = None) -> Queue:
    """Tickets to start now, in start order: of every project, or of the named one. Dead
    workers are failed first and the conductor is pinged."""
    paths = StorePaths.default()
    waiting.check_workers(paths)
    waiting.ping(paths, project)
    return compute(paths, project)


def compute(paths: StorePaths, project: str | None) -> Queue:
    """What `next_tickets` lists, read without side effects: no worker check, no ping, so
    it runs safely under the lease lock (SP11 spec §4.6)."""
    machine = settings.load(paths)
    pause = runtime.pause_state(paths)
    found = Queue()
    candidates: list[scheduler.Candidate] = []
    busy: list[scheduler.Busy] = []
    limits: dict[str, scheduler.Limits] = {}
    starts: dict[str, tuple[Ticket, str, str]] = {}
    for slug in records.scope(paths, project):
        resolved = settings.load(paths, slug)
        limits[slug] = _limits(resolved)
        docs = records.project_tickets(paths, slug)
        found.stuck += stuck(docs, slug)
        weights = scheduler.chain_weights(
            {
                doc.meta.id: doc.meta.depends_on
                for doc in docs.values()
                if doc.meta.folder is not Folder.done
            }
        )
        for doc in docs.values():
            ticket = doc.meta
            if ticket.folder is Folder.in_process:
                if lifecycle.holds_paths(resolved, ticket):
                    busy.append(scheduler.Busy(ticket.id, slug, tuple(ticket.touches)))
                _count(found, ticket.sub_status)
            elif ticket.status == "in_queue/blocked":
                found.blocked += 1
            elif ticket.status == "in_queue/ready":
                step, problem = _start(resolved, ticket, paused=pause.covers(slug))
                if step is None:
                    found.held_back[ticket.id] = problem
                    continue
                provider = _provider(resolved, step, ticket.importance.value)
                starts[ticket.id] = (ticket, step, provider)
                slot = None if provider in NO_SLOT else provider
                touches = tuple(ticket.touches)
                hitl = ticket.gate is Gate.hitl
                editing = workflow.edit_phase(resolved, ticket.workflow, step, hitl=hitl)
                candidates.append(
                    scheduler.Candidate(
                        ticket.id,
                        slug,
                        ticket.importance,
                        ticket.created,
                        touches,
                        slot,
                        editing,
                        weights.get(ticket.id, 0),
                    )
                )
    slots = runtime.load_slots(paths)
    held = [scheduler.Held(entry.project, entry.provider) for entry in slots.held]
    claims = runtime.load_claims(paths).last
    selection = scheduler.select(candidates, busy, held, _limits(machine), limits, claims)
    found.held_back |= selection.held_back
    for candidate in selection.chosen:
        ticket, step, provider = starts[candidate.id]
        found.runnable.append(
            NextTicket(
                ticket.id, candidate.project, ticket.importance.value, step, provider, ticket.title
            )
        )
    return found


def _start(resolved: Settings, ticket: Ticket, *, paused: bool) -> tuple[str | None, str]:
    """The step a claim would start with, or None and the reason the ticket waits."""
    if paused:
        return None, "paused"
    if ticket.workflow not in resolved.workflows:
        return None, f"settings have no workflow {ticket.workflow!r}"
    decision = workflow.before(resolved, lifecycle.progress_of(resolved, ticket)).decision
    if isinstance(decision, workflow.Run):
        return decision.step, ""
    if isinstance(decision, workflow.Halt) and decision.approval == "approve_step":
        return "approve", ""
    return None, decision.reason if isinstance(decision, workflow.Halt) else "every step passed"


def _provider(resolved: Settings, step: str, importance: str | None = None) -> str:
    """The CLI a step runs on: a provider, `shell`, or `user` for the approval step."""
    role = resolved.role_of(step)
    if role is None:
        return "user"
    provider, _ = split_cli(resolved.agents[role].cli_for(importance))
    return provider


def _limits(resolved: Settings) -> scheduler.Limits:
    return scheduler.Limits(
        resolved.sessions.max, resolved.sessions.per_provider, lifecycle.path_policy(resolved)
    )


def _count(found: Queue, sub_status: str) -> None:
    if sub_status in GATES:
        found.gates += 1
    elif sub_status == "paused":
        found.paused += 1
    else:
        found.running += 1
