"""What can start now: ready tickets that pass the scheduler's rules (SP3 spec §7)."""

from dataclasses import dataclass, field

from kengash_ai import scheduler, settings, workflow
from kengash_ai.model import Folder, Gate, Settings, Ticket, split_cli
from kengash_ai.ops import lifecycle, records, waiting
from kengash_ai.ops.workspace import GATES
from kengash_ai.store import runtime
from kengash_ai.store.paths import StorePaths

NO_SLOT = ("shell", "user")  # run_tests steps and the user's approval need no session


@dataclass
class NextTicket:
    id: str
    project: str
    importance: str
    step: str
    provider: str
    title: str


@dataclass
class Queue:
    runnable: list[NextTicket] = field(default_factory=list)
    held_back: dict[str, str] = field(default_factory=dict)
    blocked: int = 0
    running: int = 0
    gates: int = 0
    paused: int = 0


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
