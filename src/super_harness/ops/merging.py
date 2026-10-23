"""Merge a finished ticket (SP3 spec §9, decisions 13 and 23; system spec §5).

Rebase the ticket branch onto the base branch in its worktree, fast-forward the base
branch in the main working tree, then remove the worktree and the branch. Harness never
pushes.
"""

import contextlib
from dataclasses import dataclass

from super_harness import gitops, settings, workflow
from super_harness.model import Doc, Event, Settings, Ticket, UserError, utc_now
from super_harness.ops import lifecycle, records, slots, tickets
from super_harness.store import documents, runtime
from super_harness.store.locks import locked
from super_harness.store.paths import StorePaths
from super_harness.store.registry import load_registry

MERGEABLE = (workflow.AWAITING_MERGE, workflow.BRANCH_READY)


@dataclass
class Merged:
    id: str
    project: str
    commits: int
    base: str


def merge_ticket(ticket_id: str, *, project: str | None, by: str) -> Merged:
    """Merge the ticket; a rebase conflict sends it back to implement (exit 1)."""
    paths = StorePaths.default()
    slug, _ = records.locate_ticket(paths, ticket_id, project)
    entry = load_registry(paths).projects[slug]
    resolved = settings.load(paths, slug)
    with locked(paths.locks / f"{slug}.lock"):
        doc = _load(paths, slug, ticket_id)
        ticket = doc.meta
        if ticket.status not in MERGEABLE:
            raise UserError(
                f"{ticket_id} is {ticket.status}; merge needs awaiting_merge or branch_ready"
            )
        worktree = paths.worktree(slug, ticket_id)
        branch = ticket.branch or f"hrn/{ticket_id}"
        with locked(paths.locks / f"repo-{slug}.lock"):
            conflicts = gitops.rebase(worktree, entry.base) if worktree.exists() else []
            if conflicts:
                message = _send_back(paths, slug, resolved, doc, conflicts, entry.base, by)
                raise UserError(message)
            commits = gitops.merge_ff(entry.path, branch, entry.base)
            gitops.remove_worktree(entry.path, worktree, branch)
        before = ticket.status
        ticket.status = "done/merged"
        ticket.step = None
        ticket.updated = utc_now()
        documents.save_ticket(paths.project(slug), doc)
        everything = records.project_tickets(paths, slug) | {ticket_id: doc}
        ready, _ = tickets.refresh_queue(paths.project(slug), everything)
        runtime.drop_ticket_state(paths, ticket_id)
        slots.release(paths, ticket_id)
        reason = f"{commits} commits into {entry.base}"
        merged = lifecycle.status_event(slug, ticket, before, reason, by=by)
        events = [merged.model_copy(update={"commits": commits})]
        events += [_unblocked(slug, dependent, ticket_id) for dependent in ready]
        records.record(paths, f"harness: merge {ticket_id}", *events)
    return Merged(ticket_id, slug, commits, entry.base)


def merge_if_clean(paths: StorePaths, slug: str, ticket_id: str, *, by: str) -> str:
    """`merge.mode: auto`: merge when the main working tree is clean and on the base branch,
    otherwise leave the ticket awaiting the merge. Returns the ticket's status. The caller
    must not hold the project lock."""
    entry = load_registry(paths).projects[slug]
    on_base = gitops.current_branch(entry.path) == entry.base
    if on_base and gitops.is_clean(entry.path):
        # A conflict sends it back, or the tree changed meanwhile: its status says which.
        with contextlib.suppress(UserError):
            merge_ticket(ticket_id, project=slug, by=by)
    return _load(paths, slug, ticket_id).meta.status


def _send_back(
    paths: StorePaths,
    slug: str,
    resolved: Settings,
    doc: Doc[Ticket],
    conflicts: list[str],
    base: str,
    by: str,
) -> str:
    """Record the conflict and route the ticket back to implement (decision 23)."""
    ticket = doc.meta
    files = ", ".join(conflicts)
    doc.sections["Findings"] = (
        f"- high · {files}:0 · rebase onto {base} conflicts · resolve the conflict in implement"
    )
    steps = resolved.workflows[ticket.workflow].steps
    ticket.step = "implement" if "implement" in steps else steps[0]
    state = runtime.load_ticket_state(paths, ticket.id)
    before = ticket.status
    if ticket.loop < ticket.loop_max:
        ticket.loop += 1
        ticket.status = "in_queue/ready"
        message = f"conflict in {files}; {ticket.id} sent back to implement (loop {ticket.loop})"
        event = Event.model_validate(
            {
                "type": "ticket.recirculated",
                "project": slug,
                "ticket": ticket.id,
                "from": "merge",
                "to": ticket.step,
                "status": ticket.status,
                "loop": ticket.loop,
                "loop_max": ticket.loop_max,
                "reason": f"rebase onto {base} conflicts in {files}",
                "by": by,
            }
        )
    else:
        ticket.status = workflow.NEEDS_APPROVAL
        state.approval = "loop_cap"
        message = (
            f"conflict in {files}; {ticket.id} waits for approval at the loop cap "
            f"({ticket.loop}/{ticket.loop_max})"
        )
        event = lifecycle.status_event(slug, ticket, before, message, by=by)
    ticket.updated = utc_now()
    documents.save_ticket(paths.project(slug), doc)
    runtime.save_ticket_state(paths, ticket.id, state)
    records.record(paths, f"harness: merge conflict {ticket.id}", event)
    return message


def _unblocked(slug: str, ticket_id: str, merged: str) -> Event:
    return Event.model_validate(
        {
            "type": "ticket.moved",
            "project": slug,
            "ticket": ticket_id,
            "from": "in_queue/blocked",
            "to": "in_queue/ready",
            "why": f"{merged} merged",
            "by": "harness",
        }
    )


def _load(paths: StorePaths, slug: str, ticket_id: str) -> Doc[Ticket]:
    path = documents.find_ticket(paths.project(slug), ticket_id)
    if path is None:
        raise UserError(f"unknown ticket: {ticket_id}")
    return documents.load_ticket(path)
