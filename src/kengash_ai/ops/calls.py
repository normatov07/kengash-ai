"""Retry rules every CLI call shares: ticket steps, plan reviews and compaction (SP3 spec §5
item 5). A timeout retries once; a schema error, and an empty turn whose actions were
denied, each get one repair turn on the session; a network error gets one resumed turn
(SP12 spec §3.4)."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kengash_ai import adapters
from kengash_ai.model import Settings, StepRequest, StepResult, Usage
from kengash_ai.ops import prompts
from kengash_ai.store.paths import StorePaths

BINARIES = {"claude": "claude", "codex": "codex", "antigravity": "agy"}


@dataclass
class Called:
    """The last request of a call, its result, and the usage of every attempt."""

    request: StepRequest
    result: StepResult
    usage: Usage


def step_timeout(resolved: Settings) -> int:
    return resolved.step_timeout_min * 60


def call(
    paths: StorePaths, provider: str, request: StepRequest, next_log: Callable[[], Path]
) -> Called:
    """Run `request`; a timeout, a schema error and denied actions each get one more attempt."""
    usage = Usage()
    timed_out = repaired = unblocked = reconnected = False
    while True:
        result = adapters.get(provider, runtime=paths.runtime).run(request)
        usage = plus(usage, result.usage)
        if result.error == "network" and not reconnected:
            reconnected = True
            request = resume(request, result, prompts.NETWORK_PROMPT, next_log())
            continue
        if result.error == "timeout" and not timed_out:
            timed_out = True
            request = again(request, result, next_log())
            continue
        if result.error == "schema" and not repaired:
            repaired = True
            request = repair(request, result, result.detail, next_log())
            continue
        problem = denied(result)
        if problem is not None and not unblocked:
            unblocked = True
            request = repair(request, result, problem, next_log())
            continue
        return Called(request, result, usage)


def denied(result: StepResult) -> str | None:
    """For an empty turn whose actions the CLI denied (agy ends the turn after a denied
    terminal command): what the repair turn tells the session; None otherwise."""
    marker = "denied: "
    if result.error != "empty" or marker not in result.detail:
        return None
    actions = result.detail.split(marker, 1)[1]
    return (
        f"this step denied {actions}; those actions are not available here. "
        "Read and edit files with your file tools only"
    )


def again(request: StepRequest, result: StepResult | None, log: Path) -> StepRequest:
    """The same request once more, logging to `log`. A new claude session that the CLI
    reported, or that ran until the timeout, exists now: the retry resumes it, since
    claude refuses a `--session-id` already in use."""
    update: dict[str, Any] = {"log": log}
    fresh = result is not None and not request.resume and request.session_id is not None
    if fresh and result is not None and (result.session_id or result.error == "timeout"):
        session = result.session_id or request.session_id
        update |= {"resume": True, "session_id": session, "skill": None}
    return request.model_copy(update=update)


def repair(request: StepRequest, result: StepResult, problem: str, log: Path) -> StepRequest:
    """A resumed turn that asks the session to fix `problem`; without a session, a retry."""
    return resume(request, result, prompts.repair_prompt(problem), log)


def resume(request: StepRequest, result: StepResult, prompt: str, log: Path) -> StepRequest:
    """A resumed turn on the call's session saying `prompt`; without a session, a retry. A
    new session the CLI never reported (claude's id is made before the call) is not resumed:
    it may not exist, so the request runs again (SP12 final review)."""
    session = result.session_id or (request.session_id if request.resume else None)
    if session is None:
        return again(request, None, log)
    return request.model_copy(
        update={
            "prompt": prompt,
            "resume": True,
            "session_id": session,
            "skill": None,
            "prior_usage": result.total_usage or request.prior_usage,
            "log": log,
        }
    )


FAILURE_MAX = 300


def failure(
    provider: str,
    request: StepRequest,
    result: StepResult,
    *,
    worktree: Path | None = None,
    changed: int = 0,
) -> str:
    """One line of at most FAILURE_MAX characters naming why a call failed, where its
    output went and, for an editing step, where its changes are kept (SP12 spec §3.6)."""
    if result.error == "auth":
        return f"sign in to {BINARIES.get(provider, provider)} interactively"
    kept = f"; work kept in {worktree} ({changed} files changed)" if worktree and changed else ""
    if result.error == "timeout":
        return f"timeout: killed after {request.timeout_s} s twice; log: {request.log}{kept}"
    lines = result.detail.strip().splitlines()
    detail = lines[0].strip() if lines else ""
    tail_part = f"; log: {request.log}{kept}"
    head = f"{result.error}: "
    room = FAILURE_MAX - len(head) - len(tail_part)
    if len(detail) > room:
        detail = detail[: max(room - 1, 0)] + "…"
    return f"{head}{detail}{tail_part}"


def plus(a: Usage, b: Usage) -> Usage:
    cost = (
        None if a.cost_usd is None and b.cost_usd is None else (a.cost_usd or 0) + (b.cost_usd or 0)
    )
    return Usage(
        input=a.input + b.input,
        output=a.output + b.output,
        cache_read=a.cache_read + b.cache_read,
        cache_write=a.cache_write + b.cache_write,
        cost_usd=cost,
    )
