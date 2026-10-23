"""The step loop of a ticket job (SP3 spec §5; system spec §7.1).

A job runs steps until a gate, the end, a pause or park request, or its step budget.
Ticket and state writes happen under the project lock; CLI calls happen outside it.
"""

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from super_harness import adapters, gitops, journal, settings, workflow
from super_harness.model import (
    STEP_ROLES,
    Doc,
    Event,
    Folder,
    NeedsSetup,
    ProviderOptions,
    ProviderStatus,
    ReviewOutput,
    Running,
    SessionRef,
    Settings,
    SlotEntry,
    StepRequest,
    StepResult,
    Ticket,
    TicketState,
    Usage,
    UserError,
    WorkOutput,
    utc_now,
)
from super_harness.ops import agents, calls, lifecycle, merging, prompts, records, slots
from super_harness.ops.workspace import GATES
from super_harness.store import documents, runtime
from super_harness.store.locks import locked
from super_harness.store.paths import StorePaths
from super_harness.store.registry import load_registry

SLOT_POLL_S = 5
QUOTA_WAIT_S = 900
sleep = time.sleep


@dataclass
class JobEnd:
    status: str
    reason: str


@dataclass
class _Job:
    paths: StorePaths
    slug: str
    ticket_id: str
    repo: Path
    base: str
    detect: Callable[[str], ProviderStatus]
    merge_pending: bool = False  # every step passed under merge.mode: auto

    @property
    def worktree(self) -> Path:
        return self.paths.worktree(self.slug, self.ticket_id)


@dataclass
class _Ready:
    """A step that passed its checks and is about to run."""

    doc: Doc[Ticket]
    state: TicketState
    resolved: Settings
    step: str


@dataclass
class _Ran:
    """A step's successful CLI call, the request that made it, and what it committed."""

    pick: agents.Pick
    request: StepRequest
    result: StepResult
    usage: Usage
    loop: int
    commit: str | None = None
    files: list[gitops.FileChange] | None = None


def run_job(ticket_id: str, *, project: str | None = None, steps: int | None = None) -> JobEnd:
    """Run the ticket's steps until a gate, the end, a flag, or `steps` steps."""
    paths = StorePaths.default()
    slug, _ = records.locate_ticket(paths, ticket_id, project)
    entry = load_registry(paths).projects[slug]
    job = _Job(paths, slug, ticket_id, entry.path, entry.base, agents.detector(paths))
    _recover(job)
    done = 0
    while True:
        began = _begin(job, budget_left=steps is None or done < steps)
        if isinstance(began, JobEnd):
            return _merge_now(job, began)
        ended = _step(job, began)
        done += 1
        if ended is not None:
            return _merge_now(job, ended)


def _merge_now(job: _Job, end: JobEnd) -> JobEnd:
    """After the lock is released: merge a ticket whose last step passed under `auto`."""
    if not job.merge_pending:
        return end
    status = merging.merge_if_clean(job.paths, job.slug, job.ticket_id, by="harness")
    return JobEnd(status, "merged" if status == "done/merged" else end.reason)


def fail_job(ticket_id: str, *, project: str | None, reason: str) -> str:
    """Fail a ticket whose worker hit an unexpected error."""
    paths = StorePaths.default()
    slug, _ = records.locate_ticket(paths, ticket_id, project)
    return fail_ticket(paths, slug, ticket_id, reason)


def fail_ticket(
    paths: StorePaths,
    slug: str,
    ticket_id: str,
    reason: str,
    *,
    kind: str | None = None,
    tokens: int = 0,
) -> str:
    """Mark a running ticket failed, adding `tokens` its failed calls used; a ticket at a
    gate or outside in_process keeps its status. Returns the ticket's status afterwards."""
    with locked(_lock(paths, slug)):
        doc = _load(paths, slug, ticket_id)
        ticket = doc.meta
        if ticket.folder is not Folder.in_process or ticket.sub_status in GATES:
            return ticket.status
        ticket.tokens += tokens
        event = _set_status(paths, slug, doc, "in_process/failed", reason, kind=kind)
        slots.release(paths, ticket_id)
        records.record(paths, f"harness: {ticket_id} failed", event)
        return ticket.status


def _begin(job: _Job, *, budget_left: bool) -> _Ready | JobEnd:
    """Under the project lock: honour flags and caps, then pick the step to run."""
    paths = job.paths
    with locked(_lock(paths, job.slug)):
        doc = _load(paths, job.slug, job.ticket_id)
        ticket = doc.meta
        if ticket.folder is not Folder.in_process or ticket.sub_status in (*GATES, "paused"):
            return JobEnd(ticket.status, "not running")
        resolved = settings.load(paths, job.slug)
        if runtime.park_requested(paths, job.ticket_id):
            runtime.set_park(paths, job.ticket_id, on=False)
            return _halt(job, doc, "in_queue/parked", "parked on request")
        if runtime.pause_state(paths).covers(job.slug):
            return _halt(job, doc, "in_process/paused", "paused")
        if not budget_left:
            return _halt(job, doc, "in_process/paused", "step budget spent")
        state = runtime.load_ticket_state(paths, job.ticket_id)
        routed = workflow.before(resolved, lifecycle.progress_for(resolved, ticket, state))
        lifecycle.apply_progress(resolved, doc, state, routed.progress)
        decision = routed.decision
        if isinstance(decision, workflow.Halt):
            state.approval = decision.approval
            runtime.save_ticket_state(paths, job.ticket_id, state)
            return _halt(job, doc, decision.status, decision.reason)
        if isinstance(decision, workflow.Merge):
            runtime.save_ticket_state(paths, job.ticket_id, state)
            job.merge_pending = True
            return _halt(job, doc, workflow.AWAITING_MERGE, "every step passed")
        ticket.status = lifecycle.step_status(resolved, decision.step)
        ticket.updated = utc_now()
        documents.save_ticket(paths.project(job.slug), doc)
        runtime.save_ticket_state(paths, job.ticket_id, state)
        runtime.set_worker_step(paths, job.ticket_id, decision.step)
        return _Ready(doc, state, resolved, decision.step)


def _step(job: _Job, ready: _Ready) -> JobEnd | None:
    """Run one step's CLI call, commit its edits, then write and route its result."""
    role = STEP_ROLES[ready.step]
    assert role is not None  # the approve step halts in _begin
    try:
        pick = agents.pick(ready.resolved, role, job.detect)
    except NeedsSetup as exc:
        return _fail(job, str(exc))
    if pick.provider != "shell":
        _take_slot(job, ready, pick)
    ran = _call(job, ready, pick)
    if isinstance(ran, JobEnd):
        return ran
    if ready.step in prompts.EDIT_STEPS:
        committed = _commit(job, ready, ran)
        if isinstance(committed, JobEnd):
            return committed
    return _finish(job, ready, ran)


def _take_slot(job: _Job, ready: _Ready, pick: agents.Pick) -> None:
    entry = SlotEntry(
        provider=pick.provider,
        project=job.slug,
        ticket=job.ticket_id,
        step=ready.step,
        pid=os.getpid(),
    )
    if slots.acquire(job.paths, entry):
        return
    _update(job, ready.step, lambda doc, state: _status(doc, "in_process/waiting_slot"))
    while not slots.acquire(job.paths, entry):
        runtime.beat(job.paths, job.ticket_id)
        sleep(SLOT_POLL_S)
    step_status = lifecycle.step_status(ready.resolved, ready.step)
    _update(job, ready.step, lambda doc, state: _status(doc, step_status))


def _call(job: _Job, ready: _Ready, pick: agents.Pick) -> _Ran | JobEnd:
    """Run the step's CLI: timeouts and schema errors retry once, rate limits fall back
    or wait for the quota, other errors fail the ticket (SP3 spec §5 item 5)."""
    request = _prepare(job, ready, pick)
    usage = Usage()
    tried = {pick.provider}
    timed_out = repaired = False
    while True:
        result = adapters.get(pick.provider, runtime=job.paths.runtime).run(request)
        usage = calls.plus(usage, result.usage)
        error = result.error
        if error is None:
            return _Ran(pick, request, result, usage, ready.doc.meta.loop)
        if error == "timeout" and not timed_out:
            timed_out = True
            request = _again(job, request, result)
            continue
        if error == "schema" and not repaired:
            repaired = True
            request = _repair(job, request, result, result.detail)
            continue
        if error == "rate_limit":
            fallback = _fallback(job, ready, pick, tried)
            if fallback is not None:
                pick = fallback
                tried.add(pick.provider)
                slots.release(job.paths, job.ticket_id)
                _take_slot(job, ready, pick)
                request = _prepare(job, ready, pick)
                continue
            _wait_quota(job, ready, result)
            request = _again(job, request, result)
            continue
        if _never_started(request, result):
            _forget_session(job, ready.step, pick.role, str(request.session_id))
        return _fail(job, calls.failure(pick.provider, request, result), usage)


def _prepare(job: _Job, ready: _Ready, pick: agents.Pick) -> StepRequest:
    """Start or resume the role's session on `pick` and build the step's request."""
    ticket, step, resolved = ready.doc.meta, ready.step, ready.resolved
    role = pick.role
    ref = ticket.sessions.get(role)
    resume = resolved.sessions.reuse and ref is not None and ref.provider == pick.provider
    session_id = ref.id if resume and ref is not None else None
    if pick.provider == "claude" and not resume:
        session_id = str(uuid4())  # known before the step ends, so a killed step can resume
    start = gitops.head(job.worktree) if step in prompts.EDIT_STEPS else None
    log = _next_log(job)

    def begin(doc: Doc[Ticket], state: TicketState) -> None:
        state.running = Running(role=role, provider=pick.provider, model=pick.model, log=log)
        if start is not None:
            state.start_commit = start
        if pick.provider == "claude" and not resume and session_id is not None:
            doc.meta.sessions[role] = SessionRef(
                provider=pick.provider, model=pick.model or "default", id=session_id
            )

    _update(job, step, begin)
    ready.state = runtime.load_ticket_state(job.paths, job.ticket_id)
    _journal(job, "step.start", step=step, role=role, provider=pick.provider, loop=ticket.loop)
    if pick.provider != "shell":
        kind = "session.resumed" if resume else "session.created"
        _journal(job, kind, role=role, provider=pick.provider, session=session_id)
    return _request(job, ready, pick, session_id=session_id, resume=resume, log=log)


def _never_started(request: StepRequest, result: StepResult) -> bool:
    """A new claude session whose CLI failed before creating it (no id, no timeout)."""
    fresh = not request.resume and request.session_id is not None
    return fresh and not result.session_id and result.error != "timeout"


def _forget_session(job: _Job, step: str, role: str, session_id: str) -> None:
    """Drop the session id stored before the call, so the next run starts a new one."""

    def forget(doc: Doc[Ticket], state: TicketState) -> None:
        ref = doc.meta.sessions.get(role)
        if ref is not None and ref.id == session_id:
            del doc.meta.sessions[role]

    _update(job, step, forget)


def _again(job: _Job, request: StepRequest, result: StepResult | None = None) -> StepRequest:
    return calls.again(request, result, _next_log(job))


def _repair(job: _Job, request: StepRequest, result: StepResult, problem: str) -> StepRequest:
    return calls.repair(request, result, problem, _next_log(job))


def _fallback(job: _Job, ready: _Ready, pick: agents.Pick, tried: set[str]) -> agents.Pick | None:
    if not ready.resolved.fallback_on_rate_limit:
        return None
    try:
        return agents.pick(ready.resolved, pick.role, job.detect, skip=tried)
    except NeedsSetup:
        return None


def _wait_quota(job: _Job, ready: _Ready, result: StepResult) -> None:
    """Show `waiting_quota` and sleep until the reset time (15 minutes when unknown)."""
    _update(job, ready.step, lambda doc, state: _status(doc, "in_process/waiting_quota"))
    if result.retry_after is not None:
        remaining = max((result.retry_after - utc_now()).total_seconds(), 0.0)
    else:
        remaining = float(QUOTA_WAIT_S)
    while remaining > 0:
        nap = min(remaining, 60.0)
        sleep(nap)
        runtime.beat(job.paths, job.ticket_id)
        remaining -= nap
    step_status = lifecycle.step_status(ready.resolved, ready.step)
    _update(job, ready.step, lambda doc, state: _status(doc, step_status))


def _next_log(job: _Job) -> Path:
    """Count one more CLI call for the ticket and name its raw-output file."""
    with locked(_lock(job.paths, job.slug)):
        state = runtime.load_ticket_state(job.paths, job.ticket_id)
        state.calls += 1
        runtime.save_ticket_state(job.paths, job.ticket_id, state)
    return job.paths.logs / f"{job.ticket_id}-{state.calls}.out"


def _request(
    job: _Job,
    ready: _Ready,
    pick: agents.Pick,
    *,
    session_id: str | None,
    resume: bool,
    log: Path,
) -> StepRequest:
    ticket, sections, resolved, step = (
        ready.doc.meta,
        ready.doc.sections,
        ready.resolved,
        ready.step,
    )
    diff_stat = (
        gitops.diff(job.worktree, job.base, stat=True) if step in prompts.REVIEW_STEPS else ""
    )
    if resume:
        prompt = prompts.resumed_prompt(ticket, sections, step=step, diff_stat=diff_stat)
        skill = None
    else:
        prompt = prompts.new_prompt(
            ticket, sections, _goal(job, ticket), role=pick.role, step=step, diff_stat=diff_stat
        )
        skill = prompts.role_skill(job.paths, job.slug, resolved.agents[pick.role].skill)
    options = ProviderOptions() if pick.provider == "shell" else resolved.provider(pick.provider)
    return StepRequest(
        role=pick.role,
        cwd=job.worktree,
        prompt=prompt,
        output=prompts.output_kind(step),
        profile=prompts.profile(step),
        timeout_s=calls.step_timeout(resolved),
        log=log,
        model=pick.model,
        session_id=session_id,
        resume=resume,
        skill=skill,
        test_cmd=resolved.project.test_cmd,
        lint_cmd=resolved.project.lint_cmd,
        allow_api_key=options.allow_api_key,
        user_config=options.user_config,
        bypass=resolved.agents[pick.role].bypass_permissions,
        prior_usage=ready.state.totals.get(pick.role) if resume else None,
    )


def _commit(job: _Job, ready: _Ready, ran: _Ran) -> JobEnd | None:
    """Fold any commits the agent made, then commit the step's changes with trailers; a
    failing hook gets one repair turn on the step's session (SP3 spec decision 12)."""
    ticket = ready.doc.meta
    output = ran.result.output
    summary = output.summary if isinstance(output, WorkOutput) else ""
    first = summary.strip().splitlines()[0] if summary.strip() else ready.step
    subject = f"hrn({ticket.id}): loop {ran.loop} {ready.step}: {first}"
    trailers = {
        "Harness-Ticket": str(ticket.uuid),
        "Harness-Step": ready.step,
        "Harness-Loop": str(ran.loop),
        "Harness-Agent": ran.pick.role,
        "Harness-Model": f"{ran.pick.provider}/{ran.pick.model or 'default'}",
    }
    for attempt in (1, 2):
        _fold(job)
        try:
            ran.commit = gitops.commit_all(job.worktree, subject, trailers)
            break
        except gitops.CommitFailed as exc:
            lines = exc.output.strip().splitlines()
            if attempt == 2:
                last = lines[-1] if lines else str(exc)
                return _fail(job, f"commit failed: {last}", ran.usage)
            problem = "the commit hook failed:\n" + "\n".join(lines[-20:])
            request = _repair(job, ran.request, ran.result, problem)
            result = adapters.get(ran.pick.provider, runtime=job.paths.runtime).run(request)
            ran.usage = calls.plus(ran.usage, result.usage)
            if result.error is not None:
                return _fail(job, calls.failure(ran.pick.provider, request, result), ran.usage)
            session = result.session_id or ran.result.session_id
            ran.result = ran.result.model_copy(update={"session_id": session})
    ran.files = gitops.commit_files(job.worktree, ran.commit) if ran.commit else []
    return None


def _fold(job: _Job) -> None:
    """Undo commits the agent made during the step, keeping their changes staged."""
    start = runtime.load_ticket_state(job.paths, job.ticket_id).start_commit
    if start is not None and gitops.head(job.worktree) != start:
        gitops.reset_soft(job.worktree, start)


def _finish(job: _Job, ready: _Ready, ran: _Ran) -> JobEnd | None:
    """Under the project lock: write the step's result, route, and record it."""
    paths, step, resolved = job.paths, ready.step, ready.resolved
    pick, result = ran.pick, ran.result
    with locked(_lock(paths, job.slug)):
        doc = _load(paths, job.slug, job.ticket_id)
        ticket = doc.meta
        if ticket.folder is not Folder.in_process or ticket.step != step:
            slots.release(paths, job.ticket_id)  # the user moved it: their status stands
            return JobEnd(ticket.status, "changed while the step ran")
        state = runtime.load_ticket_state(paths, job.ticket_id)
        output = result.output
        fingerprints: tuple[str, ...] = ()
        if isinstance(output, ReviewOutput):
            verdict = output.verdict
            failing = output.findings if verdict == "fail" else []
            doc.sections["Findings"] = prompts.findings_text(failing)
            fingerprints = tuple(workflow.fingerprint(f.file, f.issue) for f in failing)
        else:
            verdict = "pass"
            if isinstance(output, WorkOutput):
                doc.sections["Handoff"] = prompts.handoff_text(output.handoff)
        tokens = ran.usage.tokens
        ticket.tokens += tokens
        line = prompts.log_line(
            utc_now(), step, pick.role, pick.provider, pick.model, verdict, tokens
        )
        doc.sections["Log"] = "\n".join(filter(None, [doc.sections.get("Log", "").strip(), line]))
        if pick.provider != "shell" and result.session_id:
            ticket.sessions[pick.role] = SessionRef(
                provider=pick.provider, model=pick.model or "default", id=result.session_id
            )
        if result.total_usage is not None:
            state.totals[pick.role] = result.total_usage
        state.running = None
        events = [_step_end(job, step, ran, verdict, fingerprints)]
        routed = workflow.after(
            resolved,
            lifecycle.progress_for(resolved, ticket, state),
            workflow.Outcome(verdict, fingerprints),
        )
        lifecycle.apply_progress(resolved, doc, state, routed.progress)
        decision = routed.decision
        end: JobEnd | None = None
        if isinstance(decision, workflow.Run):
            if ticket.loop > ran.loop:
                events.append(_recirculated(job, ticket, step, decision.step))
            ticket.status = lifecycle.step_status(resolved, decision.step)
            ticket.updated = utc_now()
            documents.save_ticket(paths.project(job.slug), doc)
        else:
            if isinstance(decision, workflow.Halt):
                status, reason = decision.status, decision.reason
                state.approval = decision.approval
            else:
                status, reason = workflow.AWAITING_MERGE, "every step passed"
                job.merge_pending = True
            events.append(_set_status(paths, job.slug, doc, status, reason))
            end = JobEnd(status, reason)
        runtime.save_ticket_state(paths, job.ticket_id, state)
        slots.release(paths, job.ticket_id)
        records.record(paths, f"harness: {job.ticket_id} {step}", *events)
    return end


def _halt(job: _Job, doc: Doc[Ticket], status: str, reason: str) -> JobEnd:
    """Stop the job at `status` (caller holds the project lock)."""
    event = _set_status(job.paths, job.slug, doc, status, reason)
    slots.release(job.paths, job.ticket_id)
    records.record(job.paths, f"harness: {job.ticket_id} {doc.meta.sub_status}", event)
    return JobEnd(status, reason)


def _fail(job: _Job, reason: str, usage: Usage | None = None) -> JobEnd:
    tokens = usage.tokens if usage is not None else 0
    status = fail_ticket(job.paths, job.slug, job.ticket_id, reason, tokens=tokens)
    return JobEnd(status, reason)


def _set_status(
    paths: StorePaths,
    slug: str,
    doc: Doc[Ticket],
    status: str,
    reason: str,
    *,
    kind: str | None = None,
) -> Event:
    ticket = doc.meta
    before = ticket.status
    ticket.status = status
    if ticket.folder is Folder.done:
        ticket.step = None
    ticket.updated = utc_now()
    documents.save_ticket(paths.project(slug), doc)
    return lifecycle.status_event(slug, ticket, before, reason, kind=kind)


def _status(doc: Doc[Ticket], status: str) -> None:
    doc.meta.status = status
    doc.meta.updated = utc_now()


def _update(job: _Job, step: str, change: Callable[[Doc[Ticket], TicketState], None]) -> None:
    """Reload the ticket and its state under the project lock, change both, save both;
    nothing changes once the user has moved the ticket off `step` (decision 26)."""
    with locked(_lock(job.paths, job.slug)):
        doc = _load(job.paths, job.slug, job.ticket_id)
        if doc.meta.folder is not Folder.in_process or doc.meta.step != step:
            return
        state = runtime.load_ticket_state(job.paths, job.ticket_id)
        change(doc, state)
        documents.save_ticket(job.paths.project(job.slug), doc)
        runtime.save_ticket_state(job.paths, job.ticket_id, state)


def _recover(job: _Job) -> None:
    """A worker that died mid-call left `state.running`: keep the session its CLI printed."""
    with locked(_lock(job.paths, job.slug)):
        state = runtime.load_ticket_state(job.paths, job.ticket_id)
        running = state.running
        if running is None:
            return
        doc = _load(job.paths, job.slug, job.ticket_id)
        if running.role not in doc.meta.sessions and running.provider != "shell":
            provider = adapters.get(running.provider, runtime=job.paths.runtime)
            session = provider.recover_session(running.log)
            if session is not None:
                doc.meta.sessions[running.role] = SessionRef(
                    provider=running.provider, model=running.model or "default", id=session
                )
                documents.save_ticket(job.paths.project(job.slug), doc)
        state.running = None
        runtime.save_ticket_state(job.paths, job.ticket_id, state)


def _goal(job: _Job, ticket: Ticket) -> str:
    try:
        _, path = records.locate_plan(job.paths, ticket.plan, job.slug)
    except UserError:  # a missing plan only costs the prompt its Goal
        return ""
    return records.load_plan(path).sections.get("Goal", "")


def _step_end(
    job: _Job, step: str, ran: _Ran, verdict: str, fingerprints: tuple[str, ...]
) -> Event:
    files = ran.files or []
    usage = ran.usage
    data: dict[str, Any] = {
        "type": "step.end",
        "project": job.slug,
        "ticket": job.ticket_id,
        "step": step,
        "role": ran.pick.role,
        "provider": ran.pick.provider,
        "model": ran.pick.model or "default",
        "session": ran.result.session_id,
        "loop": ran.loop,
        "verdict": verdict,
        "tokens": {
            "in": usage.input,
            "out": usage.output,
            "cache_read": usage.cache_read,
            "cache_write": usage.cache_write,
        },
        "duration_s": ran.result.duration_s,
        "files": len(files),
        "added": sum(f.added or 0 for f in files),
        "removed": sum(f.removed or 0 for f in files),
        "commit": ran.commit[:7] if ran.commit else None,
        "fingerprints": list(fingerprints),
    }
    return Event.model_validate(data)


def _recirculated(job: _Job, ticket: Ticket, failed: str, target: str) -> Event:
    return Event.model_validate(
        {
            "type": "ticket.recirculated",
            "project": job.slug,
            "ticket": job.ticket_id,
            "from": failed,
            "to": target,
            "loop": ticket.loop,
            "loop_max": ticket.loop_max,
        }
    )


def _journal(job: _Job, kind: str, **fields: Any) -> None:
    event = Event.model_validate(
        {"type": kind, "project": job.slug, "ticket": job.ticket_id, **fields}
    )
    journal.append(job.paths, event)


def _lock(paths: StorePaths, slug: str) -> Path:
    return paths.locks / f"{slug}.lock"


def _load(paths: StorePaths, slug: str, ticket_id: str) -> Doc[Ticket]:
    path = documents.find_ticket(paths.project(slug), ticket_id)
    if path is None:
        raise UserError(f"unknown ticket: {ticket_id}")
    return documents.load_ticket(path)
