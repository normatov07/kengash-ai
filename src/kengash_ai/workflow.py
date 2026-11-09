"""Step routing per workflow: effective steps, caps, stalls and approvals (SP3 spec §6).

Pure functions of the resolved settings and a ticket's progress; callers do the I/O.
"""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Literal

from kengash_ai.model import Settings

Approval = Literal["loop_cap", "token_cap", "approve_step", "blocked"]
Verdict = Literal["pass", "fail"]

NEEDS_APPROVAL = "in_process/needs_approval"
STALLED = "in_process/stalled"
FAILED = "in_process/failed"
AWAITING_MERGE = "in_process/awaiting_merge"
PARKED = "in_queue/parked"
BRANCH_READY = "done/branch_ready"

_DIGITS = re.compile(r"[0-9]+")
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True)
class Progress:
    """Where a ticket stands between steps; `step` is None once every step has passed."""

    workflow: str
    hitl: bool
    step: str | None
    loop: int
    loop_max: int
    tokens: int
    tokens_max: int
    streaks: Mapping[str, Mapping[str, int]] = field(default_factory=dict)
    plan_rounds: int = 0


@dataclass(frozen=True)
class Outcome:
    """A finished step: its verdict, the fingerprints of its findings, and what a work step
    said it is blocked on (its handoff's `BLOCKED:` line; SP15 spec §3.8)."""

    verdict: Verdict
    fingerprints: tuple[str, ...] = ()
    blocked: str = ""


@dataclass(frozen=True)
class Run:
    """Run `step` at `loop`."""

    step: str
    loop: int


@dataclass(frozen=True)
class Halt:
    """Stop at `status`; `approval` names what `kengash approve` grants, if anything."""

    status: str
    reason: str
    approval: Approval | None = None


@dataclass(frozen=True)
class Merge:
    """Every step passed under `merge.mode: auto`: merge if the main working tree allows."""


@dataclass(frozen=True)
class Routed:
    """A decision and the progress to store with it."""

    decision: Run | Halt | Merge
    progress: Progress


def steps_for(settings: Settings, workflow: str, *, hitl: bool) -> list[str]:
    """The steps a ticket runs: roles that are off are skipped, `review_plan` is dropped at
    `plan.review_max: 0`, and hitl tickets get `approve` after `plan` (first without one)."""
    steps = [
        step
        for step in settings.workflows[workflow].steps
        if _on(settings, step) and not (step == "review_plan" and settings.plan.review_max == 0)
    ]
    if hitl and "approve" not in steps:
        steps.insert(steps.index("plan") + 1 if "plan" in steps else 0, "approve")
    return steps


def first_step(settings: Settings, workflow: str, *, hitl: bool) -> str | None:
    steps = steps_for(settings, workflow, hitl=hitl)
    return steps[0] if steps else None


def edit_phase(settings: Settings, workflow: str, step: str | None, *, hitl: bool) -> bool:
    """`step` is in the workflow's editing phase: its first `edit`-kind step or any step after
    it (SP16 spec §3.7); False for an unknown step or a workflow without an edit step."""
    if step is None or workflow not in settings.workflows:
        return False
    order = steps_for(settings, workflow, hitl=hitl)
    edits = [index for index, name in enumerate(order) if settings.kind_of(name) == "edit"]
    return bool(edits) and step in order and order.index(step) >= edits[0]


def blocking_off(settings: Settings, workflow: str) -> str | None:
    """The first role of the workflow that is switched off although it is blocking."""
    for step in settings.workflows[workflow].steps:
        role = settings.role_of(step)
        if role is not None and settings.agents[role].blocking and not settings.agents[role].on:
            return role
    return None


def before(settings: Settings, progress: Progress) -> Routed:
    """Check the ticket's step before it runs: blocking roles, the token cap, approval."""
    role = blocking_off(settings, progress.workflow)
    if role is not None:
        return Routed(Halt(FAILED, f"role {role} is off and blocking"), progress)
    step = progress.step
    if step is None:
        return _end(settings, progress)
    if step not in steps_for(settings, progress.workflow, hitl=progress.hitl):
        if step not in settings.workflows[progress.workflow].steps:
            reason = f"workflow {progress.workflow} has no step {step}"
            return Routed(Halt(FAILED, reason), progress)
        following = _next(settings, progress, step)  # its role was switched off
        if following is None:
            return _end(settings, progress)
        step = following
    now = replace(progress, step=step)
    if now.tokens >= now.tokens_max and settings.loop_start == "auto":
        # Auto mode asks only about the loop limit (SP21 spec §3); loops still bound the spend
        now = replace(now, tokens_max=now.tokens + settings.tokens.per_ticket_max)
    if now.tokens >= now.tokens_max:
        reason = f"token cap: {now.tokens:,} of {now.tokens_max:,} used; approve with --tokens N"
        return Routed(Halt(NEEDS_APPROVAL, reason, "token_cap"), now)
    if step == "approve":
        return Routed(Halt(NEEDS_APPROVAL, "waiting for the user's approval", "approve_step"), now)
    return Routed(Run(step, now.loop), now)


def after(settings: Settings, progress: Progress, outcome: Outcome) -> Routed:
    """Route the step that just ran (`progress.step`): the first matching rule of §6 wins."""
    step = progress.step
    if step is None:
        raise ValueError("after() needs the step that ran")
    now = _count(settings, progress, step, outcome)
    if outcome.verdict == "pass" and outcome.blocked:
        return Routed(Halt(NEEDS_APPROVAL, f"blocked: {outcome.blocked}", "blocked"), now)
    if outcome.verdict == "pass":
        following = _next(settings, now, step)
        if following is None:
            return _end(settings, now)
        return Routed(Run(following, now.loop), replace(now, step=following))
    return _failed(settings, now, step)


def approve(
    settings: Settings,
    progress: Progress,
    approval: Approval,
    *,
    loops: int | None = None,
    tokens: int | None = None,
) -> Routed:
    """What the user's approval grants: more loops and the pending recirculation, more
    tokens, passing the approval step, or going on past a block: an editing step runs again
    in the same loop to finish the blocked part, any other step counts as passed."""
    if approval == "approve_step":
        return after(settings, progress, Outcome("pass"))
    if approval == "blocked":
        if progress.step is not None and settings.kind_of(progress.step) == "edit":
            return before(settings, progress)
        return after(settings, progress, Outcome("pass"))
    if approval == "loop_cap":
        grant = loops or settings.loop_grant
        now = replace(progress, loop_max=progress.loop_max + grant, loop=progress.loop + 1)
    else:
        grant = tokens or settings.tokens.per_ticket_max
        now = replace(progress, tokens_max=progress.tokens + grant)
    return before(settings, now)


def fingerprint(file: str, issue: str) -> str:
    """Identify a finding across loops by its path and text, ignoring case, numbers and spacing."""
    path = file.strip().replace("\\", "/").removeprefix("./")
    text = _SPACES.sub(" ", _DIGITS.sub("0", issue.lower())).strip()
    digest = hashlib.sha1(f"{path}\n{text}".encode(), usedforsecurity=False)
    return digest.hexdigest()[:12]


def _on(settings: Settings, step: str) -> bool:
    role = settings.role_of(step)
    return role is None or settings.agents[role].on


def _next(settings: Settings, progress: Progress, step: str) -> str | None:
    """The first step that runs after `step`, in workflow order."""
    steps = steps_for(settings, progress.workflow, hitl=progress.hitl)
    if step in steps:
        later = steps[steps.index(step) + 1 :]
    else:
        order = settings.workflows[progress.workflow].steps
        later = [name for name in order[order.index(step) + 1 :] if name in steps]
    return later[0] if later else None


def _end(settings: Settings, progress: Progress) -> Routed:
    done = replace(progress, step=None)
    if progress.hitl or settings.merge.mode == "ask":
        return Routed(Halt(AWAITING_MERGE, "every step passed"), done)
    if settings.merge.mode == "auto":
        return Routed(Merge(), done)
    return Routed(Halt(BRANCH_READY, "every step passed; the branch waits for the user"), done)


def _count(settings: Settings, progress: Progress, step: str, outcome: Outcome) -> Progress:
    """Fold a review outcome into the stall streaks and the failing plan-review rounds."""
    if settings.kind_of(step) != "review":
        return progress
    failing = outcome.verdict == "fail"
    previous = progress.streaks.get(step, {})
    streak = {fp: previous.get(fp, 0) + 1 for fp in outcome.fingerprints} if failing else {}
    rounds = progress.plan_rounds
    if failing and step == "review_plan":
        rounds += 1
    return replace(progress, streaks={**progress.streaks, step: streak}, plan_rounds=rounds)


def _out_of_tries(settings: Settings, progress: Progress, step: str, reason: str) -> Routed:
    """A ticket going nowhere: `stalled`, or in Auto mode the one question it may ask, whether to
    raise its loop limit. A raised limit goes back to the failing step's `on_fail` target with
    its counters cleared, so it tries something new (SP21 spec §3)."""
    if settings.loop_start != "auto" or not settings.loop_ask_at_cap:
        return Routed(Halt(STALLED, reason), progress)
    target = settings.workflows[progress.workflow].on_fail.get(step, step)
    back = replace(progress, step=target, plan_rounds=0, streaks={**progress.streaks, step: {}})
    return Routed(Halt(NEEDS_APPROVAL, f"loop cap: {reason}", "loop_cap"), back)


def _failed(settings: Settings, progress: Progress, step: str) -> Routed:
    limit = settings.plan.review_max
    if step == "review_plan" and progress.plan_rounds >= limit:
        reason = f"plan review failed {progress.plan_rounds} rounds (plan.review_max: {limit})"
        return _out_of_tries(settings, progress, step, reason)
    streak = progress.streaks.get(step, {})
    repeated = sorted(fp for fp, runs in streak.items() if runs >= settings.stall_repeat)
    if repeated:
        reason = f"same finding failed {settings.stall_repeat} loops in a row: "
        return _out_of_tries(settings, progress, step, reason + ", ".join(repeated))
    target = settings.workflows[progress.workflow].on_fail.get(step)
    if target is None:
        return Routed(Halt(FAILED, f"{step} failed and has no on_fail step"), progress)
    back = replace(progress, step=target)
    if step == "review_plan" and not settings.loop_count_rejected_review:
        return Routed(Run(target, back.loop), back)
    if back.loop < back.loop_max:
        back = replace(back, loop=back.loop + 1)
        return Routed(Run(target, back.loop), back)
    reason = f"loop cap: {back.loop} of {back.loop_max}"
    if settings.loop_ask_at_cap:
        return Routed(Halt(NEEDS_APPROVAL, reason, "loop_cap"), back)
    return Routed(Halt(PARKED, reason), back)
