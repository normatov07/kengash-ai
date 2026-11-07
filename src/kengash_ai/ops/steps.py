"""The step loop of a ticket job (SP3 spec §5; system spec §7.1).

A job runs steps until a gate, the end, a pause or park request, or its step budget.
Ticket and state writes happen under the project lock; CLI calls happen outside it.
"""

import contextlib
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from kengash_ai import adapters, gitops, journal, memory, scheduler, settings, workflow
from kengash_ai.model import (
    Checked,
    Doc,
    Event,
    Folder,
    Gate,
    KengashError,
    NeedsSetup,
    PlanOutput,
    ProviderOptions,
    ProviderStatus,
    ReviewOutput,
    Running,
    SentBack,
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
from kengash_ai.ops import agents, calls, checks, lifecycle, merging, prompts, records, slots
from kengash_ai.ops.workspace import GATES
from kengash_ai.store import documents, runtime
from kengash_ai.store.locks import locked
from kengash_ai.store.paths import StorePaths
from kengash_ai.store.redact import redact
from kengash_ai.store.registry import load_registry

SLOT_POLL_S = 5
PATH_POLL_S = 5  # a job waiting for another ticket's paths looks again this often (SP16)
WAITING_PATHS = "in_process/waiting_paths"
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
    checked: str | None = None  # the summary of in-step checks whose last run passed (SP15)
    hook_repaired: bool = False  # a commit-hook repair turn changed files after the checks


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
        if isinstance(began, _WaitPaths):
            runtime.beat(paths, ticket_id)
            sleep(PATH_POLL_S)
            continue
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
    status = merging.merge_if_clean(job.paths, job.slug, job.ticket_id, by="kengash")
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
        records.record(paths, f"kengash: {ticket_id} failed", event)
        return ticket.status


@dataclass(frozen=True)
class _WaitPaths:
    """The next step edits, and another ticket holds overlapping paths (SP16 spec §3.8)."""

    holder: str


def _begin(job: _Job, *, budget_left: bool) -> _Ready | JobEnd | _WaitPaths:
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
        if ticket.status == WAITING_PATHS:
            holder = _holder(paths, job.slug, resolved, ticket)
            if holder is not None:
                if state.waiting_on != holder:  # journaled once per holder
                    state.waiting_on = holder
                    runtime.save_ticket_state(paths, job.ticket_id, state)
                    _journal(
                        job,
                        "ticket.waiting",
                        step=decision.step,
                        holder=holder,
                        reason=f"touches overlap {holder}",
                    )
                return _WaitPaths(holder)
            state.waiting_on = ""
        ticket.status = lifecycle.step_status(resolved, decision.step)
        ticket.updated = utc_now()
        documents.save_ticket(paths.project(job.slug), doc)
        runtime.save_ticket_state(paths, job.ticket_id, state)
        runtime.set_worker_step(paths, job.ticket_id, decision.step)
        return _Ready(doc, state, resolved, decision.step)


def _narrow(resolved: Settings, ticket: Ticket, step: str, files: list[str]) -> int:
    """Narrow the ticket's touches to a planning step's files; the new count, or 0 when the
    touches stay (SP16 spec §3.12)."""
    hitl = ticket.gate is Gate.hitl
    paths = prompts.narrowed(files)
    if paths is None or workflow.edit_phase(resolved, ticket.workflow, step, hitl=hitl):
        return 0
    ticket.touches = paths
    return len(paths)


def _catch_up(job: _Job) -> None:
    """Start an edit from the newest base when the branch has no work yet (SP16 spec §3.11);
    a git error leaves the worktree as it is."""
    with locked(job.paths.locks / f"repo-{job.slug}.lock"), contextlib.suppress(gitops.GitError):
        gitops.catch_up(job.worktree, job.base)


def _holder(paths: StorePaths, slug: str, resolved: Settings, ticket: Ticket) -> str | None:
    """Another ticket of the project that holds paths overlapping this one's, if any."""
    for other in records.project_tickets(paths, slug).values():
        meta = other.meta
        if meta.id == ticket.id or not lifecycle.holds_paths(resolved, meta):
            continue
        if scheduler.overlaps(meta.touches, ticket.touches):
            return meta.id
    return None


def _step(job: _Job, ready: _Ready) -> JobEnd | None:
    """Run one step's CLI call, commit its edits, then write and route its result."""
    role = ready.resolved.role_of(ready.step)
    if role is None:  # the approve step halts in _begin, so only a broken workflow lands here
        return _fail(job, f"step {ready.step} has no role")
    try:
        pick = agents.pick(ready.resolved, role, job.detect)
    except NeedsSetup as exc:
        return _fail(job, str(exc))
    if pick.provider != "shell":
        _take_slot(job, ready, pick)
    if ready.resolved.kind_of(ready.step) == "edit":
        _catch_up(job)
    ran = _call(job, ready, pick)
    if isinstance(ran, JobEnd):
        return ran
    if ready.resolved.kind_of(ready.step) == "edit":
        _verify(job, ready, ran)
        committed = _commit(job, ready, ran)
        if isinstance(committed, JobEnd):
            return committed
        _remember_checks(job, ready, ran)
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
    """Run the step's CLI: timeouts retry once, schema errors and denied actions get one
    repair turn, a network error one resumed turn, rate limits and network errors fall back
    (or a rate limit waits for the quota), other errors fail the ticket, keeping the
    session the CLI opened (SP3 spec §5 item 5; SP12 spec §3.4, §3.5)."""
    request = _prepare(job, ready, pick)
    reused = _reused(job, ready, pick)
    if reused is not None:
        return _Ran(pick, request, reused, Usage(), ready.doc.meta.loop)
    usage = Usage()
    tried = {pick.provider}
    timed_out = repaired = unblocked = reconnected = False
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
        problem = calls.denied(result)
        if problem is not None and not unblocked:
            unblocked = True
            request = _repair(job, request, result, problem)
            continue
        if error == "network" and not reconnected:
            reconnected = True
            request = _resume(job, request, result, prompts.NETWORK_PROMPT)
            continue
        if error in ("rate_limit", "network"):
            fallback = _fallback(job, ready, pick, tried)
            if fallback is not None:
                pick = fallback
                tried.add(pick.provider)
                slots.release(job.paths, job.ticket_id)
                _take_slot(job, ready, pick)
                request = _prepare(job, ready, pick)
                reconnected = False
                continue
        if error == "rate_limit":
            _wait_quota(job, ready, result)
            request = _again(job, request, result)
            continue
        return _call_failed(job, ready, pick, request, result, usage)


def _call_failed(
    job: _Job,
    ready: _Ready,
    pick: agents.Pick,
    request: StepRequest,
    result: StepResult,
    usage: Usage,
) -> JobEnd:
    """Fail the ticket over a failed CLI call: keep the session it opened (else forget one
    that never started) and name the work left in the worktree (SP12 §3.5)."""
    if _never_started(request, result):
        _forget_session(job, ready.step, pick.role, str(request.session_id))
    elif result.session_id:
        _keep_session(job, ready.step, pick, result.session_id)
    reason = calls.failure(
        pick.provider, request, result, worktree=job.worktree, changed=_changed(job, ready)
    )
    return _fail(job, reason, usage)


def _changed(job: _Job, ready: _Ready) -> int:
    """How many files an editing step left changed in the worktree; 0 for other steps."""
    editing = ready.resolved.kind_of(ready.step) == "edit"
    return len(gitops.changed_files(job.worktree)) if editing else 0


def _prepare(job: _Job, ready: _Ready, pick: agents.Pick) -> StepRequest:
    """Start or resume the role's session on `pick` and build the step's request."""
    ticket, step, resolved = ready.doc.meta, ready.step, ready.resolved
    role = pick.role
    ref = ticket.sessions.get(role)
    resume = resolved.sessions.reuse and ref is not None and ref.provider == pick.provider
    session_id = ref.id if resume and ref is not None else None
    if pick.provider == "claude" and not resume:
        session_id = str(uuid4())  # known before the step ends, so a killed step can resume
    start = gitops.head(job.worktree) if resolved.kind_of(step) == "edit" else None
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
    model = None if pick.provider == "shell" else pick.model or "default"
    _journal(
        job,
        "step.start",
        step=step,
        role=role,
        provider=pick.provider,
        model=model,
        loop=ticket.loop,
    )
    if pick.provider != "shell":
        kind = "session.resumed" if resume else "session.created"
        _journal(job, kind, role=role, provider=pick.provider, session=session_id)
    return _request(job, ready, pick, session_id=session_id, resume=resume, log=log)


def _memory(job: _Job) -> str:
    """The memory digest for a new session; "" when the store cannot give one."""
    try:
        return memory.digest(job.paths, job.slug)
    except KengashError:
        return ""


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


def _keep_session(job: _Job, step: str, pick: agents.Pick, session_id: str) -> None:
    """Store the session a failed call opened, so `kengash run` resumes it (SP12 §3.5)."""

    def keep(doc: Doc[Ticket], state: TicketState) -> None:
        ref = doc.meta.sessions.get(pick.role)
        if ref is None or ref.id != session_id:
            doc.meta.sessions[pick.role] = SessionRef(
                provider=pick.provider, model=pick.model or "default", id=session_id
            )

    _update(job, step, keep)


def _resume(job: _Job, request: StepRequest, result: StepResult, prompt: str) -> StepRequest:
    return calls.resume(request, result, prompt, _next_log(job))


def _again(job: _Job, request: StepRequest, result: StepResult | None = None) -> StepRequest:
    return calls.again(request, result, _next_log(job))


def _repair(job: _Job, request: StepRequest, result: StepResult, problem: str) -> StepRequest:
    return calls.repair(request, result, problem, _next_log(job))


def _fallback(job: _Job, ready: _Ready, pick: agents.Pick, tried: set[str]) -> agents.Pick | None:
    if not ready.resolved.fallback_on_error:
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
        log = job.paths.logs / f"{job.ticket_id}-{state.calls}.out"
        if state.running is not None:  # progress reads the attempt that runs now (SP12)
            state.running = state.running.model_copy(update={"log": log})
        runtime.save_ticket_state(job.paths, job.ticket_id, state)
    return log


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
    review = resolved.kind_of(step) == "review"
    told = prompts.instruction(resolved, step)
    diff_stat = gitops.diff(job.worktree, job.base, stat=True) if review else ""
    feedback = _feedback(resolved, step, ready.state.sent_back)
    if resume:
        prompt = prompts.resumed_prompt(
            ticket,
            sections,
            step=step,
            diff_stat=diff_stat,
            instruction=told,
            review=review,
            feedback=feedback,
        )
        skill = None
    else:
        prompt = prompts.new_prompt(
            ticket,
            sections,
            _goal(job, ticket),
            role=pick.role,
            step=step,
            diff_stat=diff_stat,
            instruction=told,
            feedback=feedback,
            memory=_memory(job),
        )
        skill = prompts.role_skill(job.paths, job.slug, resolved.agents[pick.role].skill)
    if resolved.kind_of(step) == "edit" and gitops.changed_files(job.worktree):
        prompt = f"{prompts.RETRY_NOTE}\n\n{prompt}"  # a failed attempt left its changes
    options = ProviderOptions() if pick.provider == "shell" else resolved.provider(pick.provider)
    return StepRequest(
        role=pick.role,
        cwd=job.worktree,
        prompt=prompt,
        output=prompts.output_kind(step, resolved),
        profile=prompts.profile(step, resolved),
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


def _verify(job: _Job, ready: _Ready, ran: _Ran) -> None:
    """Run the project's checks after an editing step's reply; while they fail and fix turns
    remain, resume the step's session with what failed (SP15 spec §3.1). Fix turns only add
    chances: running out of them, a timeout, an unusable reply, a park request or a moved
    ticket ends the checks, and the step goes on as before. A reply that says it is BLOCKED
    goes straight to the user instead."""
    resolved, step = ready.resolved, ready.step
    output = ran.result.output
    blocked = isinstance(output, WorkOutput) and prompts.blocked_line(output.handoff)
    if blocked or not checks.wanted(resolved, ready.doc.meta, step):
        return
    if ran.result.session_id:  # a worker killed during the checks keeps the session
        _keep_session(job, step, ran.pick, ran.result.session_id)
    try:
        _check_and_fix(job, ready, ran)
    finally:
        pick = ran.pick
        working = Running(
            role=pick.role, provider=pick.provider, model=pick.model, log=ran.request.log
        )
        _set_running(job, step, working)


def _check_and_fix(job: _Job, ready: _Ready, ran: _Ran) -> None:
    resolved, step = ready.resolved, ready.step
    turns = resolved.checks.turns
    shell = adapters.get("shell", runtime=job.paths.runtime)
    for turn in range(turns + 1):
        log = _next_log(job)
        _set_running(job, step, Running(role="test-runner", provider="shell", log=log))
        before = set(gitops.untracked_files(job.worktree))
        result = shell.run(checks.request(resolved, job.worktree, log))
        gitops.drop_untracked(job.worktree, keep=before)  # what the checks wrote is no work
        verdict, summary = checks.outcome(result)
        if not _record_check(job, step, turn, result, (verdict, summary), log):
            return  # the user moved the ticket: their status stands
        if verdict == "pass":
            ran.checked = summary
            return
        if verdict != "fail" or turn == turns or runtime.park_requested(job.paths, job.ticket_id):
            return
        prompt = prompts.fix_prompt(redact(result.check_output), turn=turn + 1, turns=turns)
        if not _fix_turn(job, ready, ran, prompt):
            return


def _set_running(job: _Job, step: str, running: Running) -> None:
    """Name the call in flight, so `kengash ps`, `logs -f` and the Live tab follow it."""

    def put(doc: Doc[Ticket], state: TicketState) -> None:
        state.running = running

    _update(job, step, put)


def _record_check(
    job: _Job, step: str, turn: int, result: StepResult, said: tuple[str, str], log: Path
) -> bool:
    """Write a check run's Log line and Check output and journal `checks.end`; False when
    the user moved the ticket off the step. `said` is the run's verdict and summary."""
    verdict, summary = said

    def write(doc: Doc[Ticket], state: TicketState) -> None:
        doc.sections["Check output"] = redact(result.check_output) if verdict == "fail" else ""
        line = prompts.check_log_line(utc_now(), verdict, summary)
        doc.sections["Log"] = "\n".join(filter(None, [doc.sections.get("Log", "").strip(), line]))

    if not _update(job, step, write):
        return False
    event = Event.model_validate(
        {
            "type": "checks.end",
            "project": job.slug,
            "ticket": job.ticket_id,
            "step": step,
            "turn": turn,
            "verdict": verdict,
            "summary": summary,
            "duration_s": result.duration_s,
            "log": str(log),
        }
    )
    records.record(job.paths, f"kengash: {job.ticket_id} checks", event)
    return True


def _fix_turn(job: _Job, ready: _Ready, ran: _Ran, prompt: str) -> bool:
    """One resumed turn telling the session what the checks found; True once it replied
    validly (its reply replaces `ran`'s). Any other end keeps the last valid reply, because a
    fix turn only adds a chance: a `network` error gets one resumed turn, then any error ends
    the fix turns, carrying the CLI's usage totals so the next resume counts from them."""
    pick = ran.pick
    working = Running(role=pick.role, provider=pick.provider, model=pick.model, log=ran.request.log)
    _set_running(job, ready.step, working)
    provider = adapters.get(pick.provider, runtime=job.paths.runtime)
    request = _resume(job, ran.request, ran.result, prompt)
    result = provider.run(request)
    ran.usage = calls.plus(ran.usage, result.usage)
    if result.error == "network":
        request = _resume(job, request, result, prompts.NETWORK_PROMPT)
        result = provider.run(request)
        ran.usage = calls.plus(ran.usage, result.usage)
    session = result.session_id or ran.result.session_id
    if result.error is not None:
        totals = result.total_usage or ran.result.total_usage
        ran.result = ran.result.model_copy(update={"session_id": session, "total_usage": totals})
        return False
    ran.request, ran.result = request, result.model_copy(update={"session_id": session})
    return True


def _remember_checks(job: _Job, ready: _Ready, ran: _Ran) -> None:
    """After the commit: checks that passed on exactly this commit, for `run_tests` (SP15)."""
    if ran.checked is None or ran.hook_repaired:
        return
    record = Checked(commit=gitops.head(job.worktree), step=ready.step, summary=ran.checked)

    def put(doc: Doc[Ticket], state: TicketState) -> None:
        state.checked = record

    _update(job, ready.step, put)


def _reused(job: _Job, ready: _Ready, pick: agents.Pick) -> StepResult | None:
    """A shell check step's pass, taken from in-step checks that passed on the worktree's
    HEAD with nothing changed since; None means run the checks (SP15 spec §3.6)."""
    if pick.provider != "shell" or ready.resolved.kind_of(ready.step) != "check":
        return None
    checked = ready.state.checked
    if checked is None or checked.commit != gitops.head(job.worktree):
        return None
    if gitops.changed_files(job.worktree):
        return None
    summary = f"{checked.summary} (in {checked.step}, same commit)"
    return StepResult(output=ReviewOutput(verdict="pass", summary=summary, findings=[]))


def _feedback(resolved: Settings, step: str, sent: SentBack | None) -> prompts.Feedback:
    """The checks, and why the step runs again, for its prompt (SP15 spec §3.4)."""
    project = resolved.project
    return prompts.Feedback(
        checks=prompts.checks_block(project.test_cmd, project.lint_cmd),
        sent_back=prompts.sent_back_line(sent, check=resolved.kind_of(sent.step) == "check")
        if sent is not None
        else "",
        user=sent is not None and sent.step == "user",
        editing=resolved.kind_of(step) == "edit",
    )


def _commit(job: _Job, ready: _Ready, ran: _Ran) -> JobEnd | None:
    """Fold any commits the agent made, then commit the step's changes with trailers; a
    failing hook gets one repair turn on the step's session (SP3 spec decision 12)."""
    ticket = ready.doc.meta
    output = ran.result.output
    summary = output.summary if isinstance(output, WorkOutput) else ""
    first = summary.strip().splitlines()[0] if summary.strip() else ready.step
    subject = f"kg({ticket.id}): loop {ran.loop} {ready.step}: {first}"
    trailers = {
        f"{gitops.TRAILER}Ticket": str(ticket.uuid),
        f"{gitops.TRAILER}Step": ready.step,
        f"{gitops.TRAILER}Loop": str(ran.loop),
        f"{gitops.TRAILER}Agent": ran.pick.role,
        f"{gitops.TRAILER}Model": f"{ran.pick.provider}/{ran.pick.model or 'default'}",
    }
    for attempt in (1, 2):
        _fold(job)
        try:
            ran.commit = gitops.commit_all(job.worktree, subject, trailers)
            break
        except gitops.CommitFailed as exc:
            lines = exc.output.strip().splitlines()
            if ran.result.session_id:  # `kengash run` resumes the step's session
                _keep_session(job, ready.step, ran.pick, ran.result.session_id)
            if attempt == 2:
                last = lines[-1] if lines else str(exc)
                kept = calls.work_kept(job.worktree, _changed(job, ready))
                return _fail(job, f"commit failed: {last}{kept}", ran.usage)
            problem = "the commit hook failed:\n" + "\n".join(lines[-20:])
            ran.hook_repaired = True
            request = _repair(job, ran.request, ran.result, problem)
            provider = adapters.get(ran.pick.provider, runtime=job.paths.runtime)
            result = provider.run(request)
            ran.usage = calls.plus(ran.usage, result.usage)
            if result.error == "network":  # one resumed turn, as for the step itself
                request = _resume(job, request, result, prompts.NETWORK_PROMPT)
                result = provider.run(request)
                ran.usage = calls.plus(ran.usage, result.usage)
            if result.error is not None:
                return _call_failed(job, ready, ran.pick, request, result, ran.usage)
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
        state.sent_back = None  # this step's prompt carried it
        output = result.output
        fingerprints: tuple[str, ...] = ()
        blocked = ""
        narrowed = 0
        if isinstance(output, ReviewOutput):
            verdict = output.verdict
            failing = output.findings if verdict == "fail" else []
            doc.sections["Findings"] = prompts.findings_text(failing)
            fingerprints = tuple(workflow.fingerprint(f.file, f.issue) for f in failing)
            if resolved.kind_of(step) == "check":
                doc.sections["Check output"] = redact(result.check_output) if failing else ""
        else:
            verdict = "pass"
            if isinstance(output, WorkOutput):
                doc.sections["Handoff"] = prompts.handoff_text(output.handoff)
                blocked = prompts.blocked_line(output.handoff)
                if isinstance(output, PlanOutput):
                    narrowed = _narrow(resolved, ticket, step, output.files)
                if output.decisions:  # recorded only when the ticket merges (SP16 §3.3)
                    existing = doc.sections.get("Decisions", "")
                    doc.sections["Decisions"] = prompts.decision_lines(existing, output.decisions)
        tokens = ran.usage.tokens
        ticket.tokens += tokens
        line = prompts.log_line(
            utc_now(), step, pick.role, pick.provider, pick.model, verdict, tokens
        )
        if narrowed:
            line += f" · touches narrowed to {narrowed} files"
        if result.warning:  # the CLI's error after a valid output (SP12 spec §3.1)
            line += f" · warning: {result.warning.strip().splitlines()[0][:160]}"
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
            workflow.Outcome(verdict, fingerprints, blocked),
        )
        lifecycle.apply_progress(resolved, doc, state, routed.progress)
        if verdict == "fail" and isinstance(output, ReviewOutput) and routed.progress.step != step:
            state.sent_back = SentBack(step=step, summary=output.summary)  # also at a cap
        decision = routed.decision
        end: JobEnd | None = None
        if isinstance(decision, workflow.Run):
            if ticket.loop > ran.loop:
                events.append(_recirculated(job, ticket, step, decision.step))
            ticket.status = lifecycle.step_status(resolved, decision.step)
            hitl = ticket.gate is Gate.hitl
            if not workflow.edit_phase(
                resolved, ticket.workflow, step, hitl=hitl
            ) and workflow.edit_phase(resolved, ticket.workflow, decision.step, hitl=hitl):
                ticket.status = WAITING_PATHS  # takes its paths in _begin, under the lock
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
        records.record(paths, f"kengash: {job.ticket_id} {step}", *events)
    return end


def _halt(job: _Job, doc: Doc[Ticket], status: str, reason: str) -> JobEnd:
    """Stop the job at `status` (caller holds the project lock)."""
    event = _set_status(job.paths, job.slug, doc, status, reason)
    slots.release(job.paths, job.ticket_id)
    records.record(job.paths, f"kengash: {job.ticket_id} {doc.meta.sub_status}", event)
    return JobEnd(status, reason)


def _fail(job: _Job, reason: str, usage: Usage | None = None) -> JobEnd:
    tokens = usage.tokens if usage is not None else 0
    status = fail_ticket(job.paths, job.slug, job.ticket_id, reason, tokens=tokens)
    with locked(_lock(job.paths, job.slug)):  # the worker ends the call itself: nothing runs
        state = runtime.load_ticket_state(job.paths, job.ticket_id)
        if state.running is not None:
            state.running = None
            runtime.save_ticket_state(job.paths, job.ticket_id, state)
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


def _update(job: _Job, step: str, change: Callable[[Doc[Ticket], TicketState], None]) -> bool:
    """Reload the ticket and its state under the project lock, change both, save both;
    nothing changes once the user has moved the ticket off `step` (decision 26), and then
    the answer is False."""
    with locked(_lock(job.paths, job.slug)):
        doc = _load(job.paths, job.slug, job.ticket_id)
        if doc.meta.folder is not Folder.in_process or doc.meta.step != step:
            return False
        state = runtime.load_ticket_state(job.paths, job.ticket_id)
        change(doc, state)
        documents.save_ticket(job.paths.project(job.slug), doc)
        runtime.save_ticket_state(job.paths, job.ticket_id, state)
        return True


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
        **({"warning": ran.result.warning} if ran.result.warning else {}),
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
