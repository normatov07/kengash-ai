"""Merge a finished ticket (SP3 spec §9, decisions 13 and 23; system spec §5).

Rebase the ticket branch onto the base branch in its worktree, fast-forward the base
branch in the main working tree, then remove the worktree and the branch. Kengash never
pushes.
"""

import contextlib
from dataclasses import dataclass
from pathlib import Path

from kengash_ai import adapters, gitops, journal, memory, scheduler, settings, workflow
from kengash_ai.model import (
    Checked,
    Doc,
    Event,
    KengashError,
    ReviewOutput,
    SentBack,
    Settings,
    Ticket,
    UserError,
    utc_now,
)
from kengash_ai.ops import calls, checks, lifecycle, prompts, records, slots, tickets
from kengash_ai.store import documents, runtime
from kengash_ai.store.locks import locked
from kengash_ai.store.paths import StorePaths
from kengash_ai.store.redact import redact
from kengash_ai.store.registry import load_registry

MERGEABLE = (workflow.AWAITING_MERGE, workflow.BRANCH_READY)
# under `merge.mode: auto` kengash merges by itself: no gate until a merge cannot finish
MERGING = "every step passed; merging"
MERGING_EVENT = "ticket.merging"


@dataclass
class Merged:
    id: str
    project: str
    commits: int
    base: str
    decisions: int = 0  # ticket Decisions recorded in DECISIONS.md (SP16 spec §3.3)


def merge_ticket(ticket_id: str, *, project: str | None, by: str) -> Merged:
    """Merge the ticket; a rebase conflict, or checks that fail on a moved base, send it back
    to implement (exit 1). Merges of one project take turns on `merge-<slug>.lock`, so main
    only ever moves to a tested combination (SP16 spec §3.9)."""
    paths = StorePaths.default()
    slug, _ = records.locate_ticket(paths, ticket_id, project)
    entry = load_registry(paths).projects[slug]
    resolved = settings.load(paths, slug)
    queue_wait = calls.step_timeout(resolved) + 60  # another merge may be running checks
    with locked(paths.locks / f"merge-{slug}.lock", timeout=queue_wait):
        conflicts = _rebase(paths, slug, ticket_id, entry.base)
        if conflicts:
            _settle(paths, slug, ticket_id, entry.base, resolved, by, conflicts)
        _recheck(paths, slug, ticket_id, entry.base, resolved, by)
        return _land(paths, slug, ticket_id, entry.path, entry.base, by)


def _rebase(paths: StorePaths, slug: str, ticket_id: str, base: str) -> list[str]:
    """Rebase the ticket's branch onto `base` under the locks; on a conflict, replay it as one
    change on `base` and return the files that hold conflict markers (SP19 spec §3.1)."""
    with locked(paths.locks / f"{slug}.lock"):
        _mergeable(paths, slug, ticket_id)
        worktree = paths.worktree(slug, ticket_id)
        if not worktree.exists():
            return []
        with locked(paths.locks / f"repo-{slug}.lock"):
            if not gitops.rebase(worktree, base):
                return []
            return gitops.replay_onto(worktree, base, ticket_id)


def _settle(
    paths: StorePaths,
    slug: str,
    ticket_id: str,
    base: str,
    resolved: Settings,
    by: str,
    conflicts: list[str],
) -> None:
    """Regenerate conflicted generated files; when that settles everything, commit and let the
    merge go on, otherwise send the ticket back with the markers in place (SP19 spec §3.2).
    The generator runs without the project lock, as checks do."""
    worktree = paths.worktree(slug, ticket_id)
    policy = lifecycle.path_policy(resolved)
    generated = (
        [name for name in conflicts if scheduler.generated(name, policy)]
        if resolved.project.generate_cmd.strip()
        else []
    )
    problem = ""
    if generated:
        with locked(paths.locks / f"repo-{slug}.lock"):
            gitops.take_ours(worktree, generated)
        log = paths.logs / f"{ticket_id}-generate.out"
        log.parent.mkdir(parents=True, exist_ok=True)
        request = checks.generate_request(resolved, worktree, log)
        verdict, summary = checks.outcome(adapters.get("shell", runtime=paths.runtime).run(request))
        problem = "" if verdict == "pass" else summary
    left = [name for name in conflicts if name not in generated]
    with locked(paths.locks / f"{slug}.lock"):
        doc = _mergeable(paths, slug, ticket_id)
        if left:
            files = ", ".join(left)
            back = _Back(
                head=f"conflict in {files}",
                finding=f"- high · {files}:0 · rebase onto {base} conflicts; these files hold "
                "conflict markers · edit each file to keep both changes and remove every "
                "marker; kengash commits",
                reason=f"rebase onto {base} conflicts in {files}",
                conflicts=tuple(left),
            )
            raise UserError(_send_back(paths, slug, resolved, doc, back, by))
        if problem:
            back = _Back(
                head=f"regenerating failed after rebase onto {base}",
                finding=f"- high · project.generate_cmd:0 · {problem} · make the generator pass",
                reason=f"regenerating failed after rebase onto {base}: {problem}",
                replayed=True,
            )
            raise UserError(_send_back(paths, slug, resolved, doc, back, by))
        try:
            with locked(paths.locks / f"repo-{slug}.lock"):
                _commit_settled(worktree, doc.meta, base)
        except gitops.CommitFailed as exc:  # the worktree holds the replay: a worker can finish
            back = _Back(
                head=f"commit failed after rebase onto {base}",
                finding=f"- high · merge:0 · {exc} · make the commit hook pass",
                reason=f"commit failed after rebase onto {base}: {exc}",
                replayed=True,
            )
            raise UserError(_send_back(paths, slug, resolved, doc, back, by)) from exc


def _commit_settled(worktree: Path, ticket: Ticket, base: str) -> None:
    """Commit what the merge settled by itself, as the ticket's work."""
    trailers = {f"{gitops.TRAILER}Ticket": str(ticket.uuid), f"{gitops.TRAILER}Step": "merge"}
    gitops.commit_all(worktree, f"kg({ticket.id}): settle conflicts with {base}", trailers)


def _recheck(
    paths: StorePaths, slug: str, ticket_id: str, base: str, resolved: Settings, by: str
) -> None:
    """Run the project's checks on the rebased branch unless they last passed on exactly this
    commit (`TicketState.checked`), so a retry after checks that never finished tests again;
    without the project lock. A failure sends the ticket back, checks that cannot run leave
    it awaiting the merge, a pass is remembered (SP16 spec §3.9)."""
    worktree = paths.worktree(slug, ticket_id)
    with locked(paths.locks / f"{slug}.lock"):
        ticket = _mergeable(paths, slug, ticket_id).meta
        tested = runtime.load_ticket_state(paths, ticket_id).checked
    if not worktree.exists() or not checks.configured(resolved, ticket):
        return
    head = gitops.head(worktree)
    if tested is not None and tested.commit == head:
        return
    log = paths.logs / f"{ticket_id}-merge.out"
    log.parent.mkdir(parents=True, exist_ok=True)
    request = checks.request(resolved, worktree, log)
    # no check place: this runs under the merge lock, and waiting for one would stall the queue
    result = adapters.get("shell", runtime=paths.runtime).run(request)
    verdict, summary = checks.outcome(result)
    event = {"type": "checks.end", "project": slug, "ticket": ticket_id, "step": "merge"}
    journal.append(
        paths,
        Event.model_validate(
            {**event, "turn": 0, "verdict": verdict, "summary": summary, "by": by}
        ),
    )
    if verdict == "pass":
        with locked(paths.locks / f"{slug}.lock"):
            if resolved.project.generate_cmd.strip():  # the generator may have changed files
                with locked(paths.locks / f"repo-{slug}.lock"):
                    _commit_settled(worktree, _load(paths, slug, ticket_id).meta, base)
                head = gitops.head(worktree)
            state = runtime.load_ticket_state(paths, ticket_id)
            state.checked = Checked(commit=head, step="merge", summary=summary)
            runtime.save_ticket_state(paths, ticket_id, state)
        return
    if verdict != "fail" or not isinstance(result.output, ReviewOutput):
        raise UserError(f"{ticket_id}: checks could not run after rebase onto {base}: {summary}")
    back = _Back(
        head=f"checks failed after rebase onto {base}",
        finding=prompts.findings_text(result.output.findings),
        reason=f"checks failed after rebase onto {base}: {summary}",
        check_output=result.check_output,
    )
    with locked(paths.locks / f"{slug}.lock"):
        doc = _mergeable(paths, slug, ticket_id)
        raise UserError(_send_back(paths, slug, resolved, doc, back, by))


def _land(paths: StorePaths, slug: str, ticket_id: str, repo: Path, base: str, by: str) -> Merged:
    """Fast-forward `base` to the ticket's branch, remove the worktree, mark it merged."""
    with locked(paths.locks / f"{slug}.lock"):
        doc = _mergeable(paths, slug, ticket_id)
        ticket = doc.meta
        worktree = paths.worktree(slug, ticket_id)
        branch = ticket.branch or f"kg/{ticket_id}"
        with locked(paths.locks / f"repo-{slug}.lock"):
            if gitops.branch_exists(repo, branch) and not gitops.contains(repo, base, branch):
                raise UserError(f"{base} moved; run kengash merge {ticket_id} again")
            commits = gitops.merge_ff(repo, branch, base)
            gitops.remove_worktree(repo, worktree, branch)
            gitops.drop_conflict_ref(repo, ticket_id)
        before = ticket.status
        ticket.status = "done/merged"
        ticket.step = None
        ticket.updated = utc_now()
        documents.save_ticket(paths.project(slug), doc)
        everything = records.project_tickets(paths, slug) | {ticket_id: doc}
        ready, _ = tickets.refresh_queue(paths.project(slug), everything)
        runtime.drop_ticket_state(paths, ticket_id)
        slots.release(paths, ticket_id)
        reason = f"{commits} commits into {base}"
        merged = lifecycle.status_event(slug, ticket, before, reason, by=by)
        events = [merged.model_copy(update={"commits": commits})]
        events += [_unblocked(slug, dependent, ticket_id) for dependent in ready]
        records.record(paths, f"kengash: merge {ticket_id}", *events)
    recorded = _record_decisions(paths, slug, ticket_id, doc.sections.get("Decisions", ""), by)
    return Merged(ticket_id, slug, commits, base, recorded)


def _mergeable(paths: StorePaths, slug: str, ticket_id: str) -> Doc[Ticket]:
    doc = _load(paths, slug, ticket_id)
    if doc.meta.status not in MERGEABLE:
        raise UserError(
            f"{ticket_id} is {doc.meta.status}; merge needs awaiting_merge or branch_ready"
        )
    return doc


def _record_decisions(paths: StorePaths, slug: str, ticket_id: str, section: str, by: str) -> int:
    """Record the merged ticket's proposed decisions in DECISIONS.md: an ADR lands with its
    code (SP16 spec §3.3). A line memory refuses is skipped; the merge already stands."""
    recorded = 0
    for line in section.splitlines():
        decision, why, rejected = memory.parse_decision(line)
        if not decision:
            continue
        with contextlib.suppress(UserError):
            recorded += memory.add(  # fit: a line stored before 0.6.0 may be too long
                paths,
                prompts.fit(decision),
                prompts.fit(why) or f"ticket {ticket_id}",
                decision=True,
                rejected=prompts.fit(rejected) or None,
                project=slug,
                by=by,
            ).added
    return recorded


def merge_if_clean(paths: StorePaths, slug: str, ticket_id: str, *, by: str) -> str:
    """`merge.mode: auto`: merge when the main working tree is clean and on the base branch,
    otherwise leave the ticket awaiting the merge. Returns the ticket's status. The caller
    must not hold the project lock."""
    entry = load_registry(paths).projects[slug]
    current = gitops.current_branch(entry.path)
    why = ""
    if current != entry.base:
        why = f"main working tree is on {current or 'a detached HEAD'}"
    elif not gitops.is_clean(entry.path):
        why = "main working tree has changes"
    else:
        # A conflict or failed checks send it back: its status says so. Anything else that
        # stops the merge (checks that cannot run, a busy queue) leaves it for the user.
        try:
            merge_ticket(ticket_id, project=slug, by=by)
        except KengashError as exc:
            why = f"the merge did not finish: {exc}"
    doc = _load(paths, slug, ticket_id)
    if doc.meta.status == workflow.AWAITING_MERGE:  # now it is the user's gate (SP16 §3.10)
        reason = f"{why or 'the merge did not finish'}; merge waits for you"
        gate = lifecycle.status_event(slug, doc.meta, doc.meta.status, reason, by=by)
        journal.append(paths, gate)
    return doc.meta.status


@dataclass(frozen=True)
class _Back:
    """Why a merge sends its ticket back: the message head, the Findings, the event reason
    and, for failed checks, their digest."""

    head: str
    finding: str
    reason: str
    check_output: str = ""
    conflicts: tuple[str, ...] = ()  # files left with conflict markers (SP19 spec §3.1)
    replayed: bool = False  # the worktree holds a replay though no marker is left


def _send_back(
    paths: StorePaths, slug: str, resolved: Settings, doc: Doc[Ticket], back: _Back, by: str
) -> str:
    """Route the ticket back to implement with the reason, or to the loop cap's approval
    (decision 23; SP16 spec §3.9)."""
    ticket = doc.meta
    doc.sections["Findings"] = back.finding
    doc.sections["Check output"] = redact(back.check_output)
    steps = resolved.workflows[ticket.workflow].steps
    ticket.step = "implement" if "implement" in steps else steps[0]
    state = runtime.load_ticket_state(paths, ticket.id)
    state.sent_back = SentBack(step="merge", summary=back.reason)
    state.conflicts = list(back.conflicts)
    # a conflict is no rework, so a loop would be the wrong price (SP19 spec §3.1)
    free = (back.replayed or bool(back.conflicts)) and (
        state.conflict_turns < resolved.merge.conflict_turns
    )
    state.conflict_turns += int(free)
    before = ticket.status
    if free or ticket.loop < ticket.loop_max:
        ticket.loop += int(not free)
        ticket.status = "in_queue/ready"
        message = f"{back.head}; {ticket.id} sent back to implement (loop {ticket.loop})"
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
                "reason": back.reason,
                "by": by,
            }
        )
    else:
        ticket.status = workflow.NEEDS_APPROVAL
        state.approval = "loop_cap"
        message = (
            f"{back.head}; {ticket.id} waits for approval at the loop cap "
            f"({ticket.loop}/{ticket.loop_max})"
        )
        event = lifecycle.status_event(slug, ticket, before, message, by=by)
    ticket.updated = utc_now()
    documents.save_ticket(paths.project(slug), doc)
    runtime.save_ticket_state(paths, ticket.id, state)
    records.record(paths, f"kengash: merge sent {ticket.id} back", event)
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
            "by": "kengash",
        }
    )


def _load(paths: StorePaths, slug: str, ticket_id: str) -> Doc[Ticket]:
    path = documents.find_ticket(paths.project(slug), ticket_id)
    if path is None:
        raise UserError(f"unknown ticket: {ticket_id}")
    return documents.load_ticket(path)
