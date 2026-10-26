"""Plan review (SP3 spec decisions 14, 28 to 30): who reviews, the round a `plan-review`
worker runs, and `harness plan review`, which starts the job and waits for its round."""

import contextlib
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from kengash_ai import journal, memory, settings, workflow
from kengash_ai.model import (
    PLAN_SECTIONS,
    Doc,
    Event,
    HarnessError,
    NeedsSetup,
    NeedsUser,
    Plan,
    PlanStatus,
    ProviderStatus,
    ReviewOutput,
    SessionRef,
    Settings,
    SlotEntry,
    StepRequest,
    StepResult,
    Usage,
    UserError,
    WaitTimeout,
    split_cli,
    utc_now,
)
from kengash_ai.ops import agents, calls, jobs, prompts, records, slots
from kengash_ai.store import documents, runtime
from kengash_ai.store.locks import locked
from kengash_ai.store.paths import StorePaths
from kengash_ai.store.registry import load_registry

ROLE = "plan-reviewer"
JOB = "plan-review"
PROVIDERS = ("claude", "codex", "antigravity")
CONDUCTORS = {
    "claude": "claude",
    "codex": "codex",
    "agy": "antigravity",
    "antigravity": "antigravity",
}
DECISION_LINES = 40
REVIEWED = [name for name in PLAN_SECTIONS if name not in ("Prompt", "Review log")]


@dataclass
class ReviewRound:
    """One finished round: its verdict and its Review log finding lines."""

    id: str
    project: str
    round: int
    max: int
    verdict: str
    findings: list[str] = field(default_factory=list)
    reviewer: str = ""
    warning: str = ""

    @property
    def used_up(self) -> bool:
        """The last round failed: only the user can approve or reject now."""
        return self.verdict == "fail" and self.round >= self.max


def review_plan(
    plan_id: str, *, project: str | None, by: str, timeout: float, poll_s: float = 0.5
) -> ReviewRound:
    """Run the plan's next review round and wait for it (decision 28): attach to a running
    round, reprint a round that has its verdict, or start one on the chosen reviewer."""
    paths = StorePaths.default()
    slug, path = records.locate_plan(paths, plan_id, project)
    resolved = settings.load(paths, slug)
    limit = resolved.plan.review_max
    if limit == 0:
        raise UserError(f"plan review is off (plan.review_max: 0); approve plan {plan_id} directly")
    cursor = journal.end(paths)  # before the job starts, so its end cannot slip past
    warning = ""
    with locked(_lock(paths, slug)):
        doc = records.load_plan(path)
        plan = doc.meta
        number = plan.review.round + 1
        if jobs.alive(paths, plan_id) is None:
            if plan.status not in (PlanStatus.draft, PlanStatus.in_review):
                raise UserError(
                    f"plan {plan_id} is {plan.status.value}; only a draft plan can be reviewed"
                )
            if plan.review.verdict is not None:
                return _round(slug, doc, plan.review.round)
            if plan.review.round >= limit:
                raise NeedsUser(used_up_message(plan.review.round, limit))
            if not any(doc.sections.get(name, "").strip() for name in REVIEWED):
                raise UserError(
                    f"plan {plan_id} has nothing to review yet; "
                    f"save its sections with: harness plan save {plan_id}"
                )
            pick, warning = choose_reviewer(
                resolved, conductor_provider(by), agents.detector(paths)
            )
            reviewer = f"{pick.provider}/{pick.model}" if pick.model else pick.provider
            plan.review.max, plan.review.reviewer = limit, reviewer
            plan.status = PlanStatus.in_review
            plan.updated = utc_now()
            documents.save_plan(paths.project(slug), doc)
            jobs.start(paths, JOB, plan_id, slug, [JOB, plan_id, "--project", slug])
            started = Event.model_validate(
                {
                    "type": "worker.started",
                    "project": slug,
                    "plan": plan_id,
                    "job": JOB,
                    "round": number,
                    "reviewer": reviewer,
                    "by": by,
                }
            )
            records.record(paths, f"harness: plan review {plan_id}", started)

    def ended(event: Event) -> bool:
        if event.plan != plan_id:
            return False
        extra = event.model_extra or {}
        if event.type == "plan.reviewed":
            return bool(extra.get("round") == number)
        return event.type == "worker.exited" and extra.get("job") == JOB

    end = jobs.await_event(paths, cursor, ended, JOB, plan_id, timeout=timeout, poll_s=poll_s)
    if end is None:
        raise WaitTimeout(
            f"plan {plan_id} review round {number} is still running; "
            f"run harness plan review {plan_id} again to keep waiting"
        )
    if end.type == "worker.exited":
        raise UserError(f"plan {plan_id} review failed: {(end.model_extra or {}).get('reason')}")
    return _round(slug, records.load_plan(path), number, warning)


def conductor_provider(by: str) -> str | None:
    """The conductor's provider: `--by` (default $KENGASH_AGENT, then $HARNESS_AGENT) when it
    names an agent CLI, else claude when running inside Claude Code."""
    found = CONDUCTORS.get(by)
    if found is None and by in ("", "unknown") and os.environ.get("CLAUDECODE") == "1":
        return "claude"
    return found


def choose_reviewer(
    resolved: Settings, conductor: str | None, detect: Callable[[str], ProviderStatus]
) -> tuple[agents.Pick, str]:
    """The reviewer and a warning: `plan.reviewer` when it names a provider; else the
    plan-reviewer's chain without the conductor's provider, then any other usable provider,
    then the conductor's own provider with a warning."""
    if not resolved.agents[ROLE].on:
        raise UserError("the plan-reviewer agent is off; approve the plan with --skip-review")
    named = resolved.plan.reviewer
    if named != "different-provider":
        provider, model = split_cli(named)
        problem = agents.problem(provider, detect)
        if problem is not None:
            raise NeedsSetup(f"plan review cannot run: {problem}")
        return agents.Pick(ROLE, provider, model, False), ""
    if conductor is None:
        return agents.pick(resolved, ROLE, detect), ""
    with contextlib.suppress(NeedsSetup):
        return agents.pick(resolved, ROLE, detect, skip={conductor}), ""
    for provider in PROVIDERS:
        if provider != conductor and agents.problem(provider, detect) is None:
            return agents.Pick(ROLE, provider, None, True), ""
    pick = agents.pick(resolved, ROLE, detect)
    return (
        pick,
        f"reviewed on {pick.provider}, the conductor's provider: no other provider is signed in",
    )


def run_review(plan_id: str, *, project: str | None) -> str:
    """One review round of an `in_review` plan (the worker's job). Journals exactly one of
    `plan.reviewed` or `worker.exited`; returns a line for the worker log."""
    paths = StorePaths.default()
    slug, path = records.locate_plan(paths, plan_id, project)
    repo = load_registry(paths).projects[slug].path
    resolved = settings.load(paths, slug)
    with locked(_lock(paths, slug)):
        doc = records.load_plan(path)
        plan = doc.meta
        if plan.status is not PlanStatus.in_review or plan.review.verdict is not None:
            return _exit(paths, slug, plan_id, "the plan changed before its review started")
        number, since = plan.review.round + 1, plan.updated
        reviewer = plan.review.reviewer or resolved.agents[ROLE].cli
    provider, model = split_cli(reviewer)
    problem = agents.problem(provider, agents.detector(paths))
    if problem is not None:
        return _exit(paths, slug, plan_id, problem)
    entry = SlotEntry(
        provider=provider, project=slug, ticket=plan_id, step="review_plan", pid=os.getpid()
    )
    jobs.take_slot(paths, entry)
    try:
        request = _request(paths, slug, repo, resolved, doc, number, provider, model)
        called = calls.call(paths, provider, request, lambda: _next_log(paths, plan_id))
    finally:
        slots.release(paths, plan_id)
    result, output = called.result, called.result.output
    if result.error is not None or not isinstance(output, ReviewOutput):
        if request.resume:
            _forget_session(paths, slug, path, request.session_id)
        return _exit(paths, slug, plan_id, calls.failure(provider, called.request, result))
    with locked(_lock(paths, slug)):
        doc = records.load_plan(path)
        plan = doc.meta
        if plan.status is not PlanStatus.in_review or plan.updated != since:
            reason = f"the plan changed during its review; run: harness plan review {plan_id}"
            return _exit(paths, slug, plan_id, reason)
        plan.review.round, plan.review.verdict = number, output.verdict
        if result.session_id:
            plan.review.session = SessionRef(
                provider=provider, model=model or "default", id=result.session_id
            )
        log = doc.sections.get("Review log", "").strip("\n")
        lines = prompts.review_log_lines(number, output)
        doc.sections["Review log"] = "\n".join(filter(None, [log, *lines]))
        plan.updated = utc_now()
        documents.save_plan(paths.project(slug), doc)
        if result.total_usage is not None:
            state = runtime.load_ticket_state(paths, plan_id)
            state.totals[ROLE] = result.total_usage
            runtime.save_ticket_state(paths, plan_id, state)
        event = _reviewed(slug, plan, output, reviewer, result, called.usage)
        records.record(paths, f"harness: plan review {plan_id} round {number}", event)
    return f"{plan_id}: round {number} {output.verdict}"


def fail_review(plan_id: str, *, project: str | None, reason: str) -> None:
    """End a review job that hit an unexpected error."""
    paths = StorePaths.default()
    slug, _ = records.locate_plan(paths, plan_id, project)
    slots.release(paths, plan_id)
    _exit(paths, slug, plan_id, reason)


def _exit(paths: StorePaths, slug: str, plan_id: str, reason: str) -> str:
    """Journal the end of a job that produced no round."""
    journal.append(paths, jobs.exited(JOB, plan_id, slug, reason))
    return f"{plan_id}: review ended: {reason}"


def _round(slug: str, doc: Doc[Plan], number: int, warning: str = "") -> ReviewRound:
    review = doc.meta.review
    prefix, passed = f"- round {number} · ", f"- round {number} · pass · "
    lines = doc.sections.get("Review log", "").splitlines()
    findings = [line for line in lines if line.startswith(prefix) and not line.startswith(passed)]
    return ReviewRound(
        doc.meta.id,
        slug,
        number,
        review.max,
        review.verdict or "",
        findings,
        review.reviewer or "",
        warning,
    )


def used_up_message(rounds: int, limit: int) -> str:
    """What the conductor tells the user once the review rounds are used up."""
    return (
        f"review rounds used up ({rounds}/{limit}): "
        "the user approves the plan as it is or rejects it"
    )


def _request(
    paths: StorePaths,
    slug: str,
    repo: Path,
    resolved: Settings,
    doc: Doc[Plan],
    number: int,
    provider: str,
    model: str | None,
) -> StepRequest:
    """Resume the plan's reviewer session on the same provider, else start one."""
    plan = doc.meta
    agent = resolved.agents[ROLE]
    ref = plan.review.session
    resume = resolved.sessions.reuse and ref is not None and ref.provider == provider
    if resume and ref is not None:
        session_id: str | None = ref.id
    else:
        session_id = str(uuid4()) if provider == "claude" else None
    decisions = "" if resume else _decisions(paths, slug)
    prompt = prompts.plan_review_prompt(plan, doc.sections, decisions, round=number, resumed=resume)
    options = resolved.provider(provider)
    prior = runtime.load_ticket_state(paths, plan.id).totals.get(ROLE) if resume else None
    return StepRequest(
        role=ROLE,
        cwd=repo,
        prompt=prompt,
        output="review",
        profile="read_only",
        timeout_s=calls.step_timeout(resolved),
        log=_next_log(paths, plan.id),
        model=model,
        session_id=session_id,
        resume=resume,
        skill=None if resume else prompts.role_skill(paths, slug, agent.skill),
        allow_api_key=options.allow_api_key,
        user_config=options.user_config,
        bypass=agent.bypass_permissions,
        prior_usage=prior,
    )


def _decisions(paths: StorePaths, slug: str) -> str:
    """The newest project and global DECISIONS.md entries."""
    try:
        text = memory.show(paths, decisions=True, project=slug)
    except HarnessError:
        return ""
    entries = [line for line in text.splitlines() if line.startswith("- ")]
    return "\n".join(entries[-DECISION_LINES:])


def _next_log(paths: StorePaths, plan_id: str) -> Path:
    state = runtime.load_ticket_state(paths, plan_id)
    state.calls += 1
    runtime.save_ticket_state(paths, plan_id, state)
    return paths.logs / f"{plan_id}-{state.calls}.out"


def _forget_session(paths: StorePaths, slug: str, path: Path, session_id: str | None) -> None:
    """A resumed round that failed may have lost its session: the next round starts anew."""
    with locked(_lock(paths, slug)):
        doc = records.load_plan(path)
        ref = doc.meta.review.session
        if ref is not None and ref.id == session_id:
            doc.meta.review.session = None
            documents.save_plan(paths.project(slug), doc)


def _reviewed(
    slug: str,
    plan: Plan,
    output: ReviewOutput,
    reviewer: str,
    result: StepResult,
    usage: Usage,
) -> Event:
    summary = " ".join(output.summary.split())
    return Event.model_validate(
        {
            "type": "plan.reviewed",
            "project": slug,
            "plan": plan.id,
            "round": plan.review.round,
            "max": plan.review.max,
            "verdict": output.verdict,
            "summary": summary,
            "findings": len(output.findings),
            "fingerprints": [workflow.fingerprint(f.file, f.issue) for f in output.findings],
            "reviewer": reviewer,
            "session": result.session_id,
            "tokens": {
                "in": usage.input,
                "out": usage.output,
                "cache_read": usage.cache_read,
                "cache_write": usage.cache_write,
            },
            "duration_s": result.duration_s,
        }
    )


def _lock(paths: StorePaths, slug: str) -> Path:
    return paths.locks / f"{slug}.lock"
