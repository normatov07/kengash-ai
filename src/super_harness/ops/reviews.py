"""Plan review (SP3 spec decisions 14, 28 to 30): who reviews, and the round a
`plan-review` worker runs."""

import contextlib
import os
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from super_harness import journal, memory, settings, workflow
from super_harness.model import (
    Doc,
    Event,
    HarnessError,
    NeedsSetup,
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
    split_cli,
    utc_now,
)
from super_harness.ops import agents, calls, jobs, prompts, records, slots
from super_harness.store import documents, runtime
from super_harness.store.locks import locked
from super_harness.store.paths import StorePaths
from super_harness.store.registry import load_registry

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


def conductor_provider(by: str) -> str | None:
    """The conductor's provider: `--by` (default $HARNESS_AGENT) when it names an agent CLI,
    else claude when running inside Claude Code."""
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
