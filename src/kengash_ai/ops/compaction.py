"""Memory compaction (SP3 spec decision 31): the `compact` worker's job, its start from
`memory add`, and `kengash memory compact`, which waits for it."""

import os
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any
from uuid import uuid4

from kengash_ai import journal, memory, settings
from kengash_ai.model import (
    CompactOutput,
    Event,
    NeedsSetup,
    SlotEntry,
    StepRequest,
    UserError,
    WaitTimeout,
    split_cli,
)
from kengash_ai.ops import agents, calls, jobs, prompts, slots
from kengash_ai.store import runtime
from kengash_ai.store.locks import locked
from kengash_ai.store.paths import StorePaths

ROLE = "compactor"
JOB = "compact"


def compact_memory(*, timeout: float, poll_s: float = 0.5) -> memory.Compaction:
    """Start the compaction job, or join the running one, and wait for its result."""
    paths = StorePaths.default()
    if not paths.memory.is_dir():
        raise NeedsSetup("no store yet; run: kengash init")
    provider, _ = split_cli(settings.load(paths).memory.compactor)
    with _lock(paths):
        # under the lock a worker is either running or has ended and dropped its record
        # (`_ended_here`), so the cursor sits before the end of the job this call waits for
        cursor = journal.end(paths)
        if jobs.alive(paths, jobs.COMPACT) is None:
            problem = agents.problem(provider, agents.detector(paths))
            if problem is not None:
                raise NeedsSetup(f"compaction cannot run: {problem}")
            jobs.start(paths, JOB, jobs.COMPACT, "", [JOB])
    end = jobs.await_event(paths, cursor, _ended, JOB, jobs.COMPACT, timeout=timeout, poll_s=poll_s)
    if end is None:
        raise WaitTimeout(
            "MEMORY.md compaction is still running; "
            "run kengash memory compact again to keep waiting"
        )
    extra = end.model_extra or {}
    if end.type == "worker.exited":
        raise UserError(f"compaction failed: {extra.get('reason')}")
    return memory.Compaction(
        int(extra["before"]),
        int(extra["after"]),
        bool(extra["accepted"]),
        str(extra.get("reason") or ""),
    )


def start_background(paths: StorePaths) -> bool:
    """Start the compaction job unless it runs already; True once it runs."""
    with _lock(paths):
        if jobs.alive(paths, jobs.COMPACT) is None:
            jobs.start(paths, JOB, jobs.COMPACT, "", [JOB])
    return True


def start_checked() -> bool:
    """Start compaction in the background, or leave the running one, once the compactor's
    CLI can run (NeedsSetup naming why not); the job journals `memory.compacted`."""
    paths = StorePaths.default()
    if not paths.memory.is_dir():
        raise NeedsSetup("no store yet; run: kengash init")
    provider, _ = split_cli(settings.load(paths).memory.compactor)
    problem = agents.problem(provider, agents.detector(paths))
    if problem is not None:
        raise NeedsSetup(f"compaction cannot run: {problem}")
    return start_background(paths)


def run_compaction() -> str:
    """Compact MEMORY.md on `memory.compactor` (the worker's job). Journals exactly one of
    `memory.compacted` or `worker.exited`; returns a line for the worker log."""
    paths = StorePaths.default()
    resolved = settings.load(paths)
    cap = resolved.memory.compact_at_lines
    provider, model = split_cli(resolved.memory.compactor)
    problem = agents.problem(provider, agents.detector(paths))
    if problem is not None:
        return _exit(paths, problem)
    snapshot = (paths.memory / "MEMORY.md").read_text(encoding="utf-8")
    entry = SlotEntry(provider=provider, project="", ticket=jobs.COMPACT, step=JOB, pid=os.getpid())
    jobs.take_slot(paths, entry)
    try:
        options = resolved.provider(provider)
        request = StepRequest(
            role=ROLE,
            cwd=paths.memory,
            prompt=prompts.compact_prompt(snapshot, cap=cap),
            output="compact",
            profile="read_only",
            timeout_s=calls.step_timeout(resolved),
            log=_next_log(paths),
            model=model,
            session_id=str(uuid4()) if provider == "claude" else None,
            allow_api_key=options.allow_api_key,
            user_config=options.user_config,
        )
        called = calls.call(paths, provider, request, lambda: _next_log(paths))
    finally:
        slots.release(paths, jobs.COMPACT)
    result, output = called.result, called.result.output
    if result.error is not None or not isinstance(output, CompactOutput):
        return _exit(paths, calls.failure(provider, called.request, result))
    usage = called.usage
    detail: dict[str, Any] = {
        "provider": provider,
        "model": model or "default",
        "session": result.session_id,
        "tokens": {
            "in": usage.input,
            "out": usage.output,
            "cache_read": usage.cache_read,
            "cache_write": usage.cache_write,
        },
        "duration_s": result.duration_s,
    }
    with _lock(paths):
        outcome = memory.apply_compaction(paths, snapshot, output.text, cap=cap, detail=detail)
        jobs.forget(jobs.COMPACT)
    if outcome.accepted:
        return f"MEMORY.md {outcome.before} → {outcome.after} lines"
    return f"MEMORY.md kept ({outcome.before} lines): {outcome.reason}"


def fail_compaction(reason: str) -> None:
    """End a compaction job that hit an unexpected error."""
    paths = StorePaths.default()
    slots.release(paths, jobs.COMPACT)
    _exit(paths, reason)


def _ended(event: Event) -> bool:
    if event.type == "memory.compacted":
        return True
    return event.type == "worker.exited" and (event.model_extra or {}).get("job") == JOB


def _exit(paths: StorePaths, reason: str) -> str:
    with _lock(paths):
        journal.append(paths, jobs.exited(JOB, jobs.COMPACT, None, reason))
        jobs.forget(jobs.COMPACT)
    return f"compaction ended: {reason}"


def _lock(paths: StorePaths) -> AbstractContextManager[None]:
    """Orders a job's start against its end: the worker journals its end and drops its
    record under this lock, so a caller never joins a worker that has already ended
    (CI 2026-11-07: the next `memory compact` joined one and reported "worker died")."""
    return locked(paths.locks / "compact.lock")


def _next_log(paths: StorePaths) -> Path:
    state = runtime.load_ticket_state(paths, jobs.COMPACT)
    state.calls += 1
    runtime.save_ticket_state(paths, jobs.COMPACT, state)
    return paths.logs / f"{jobs.COMPACT}-{state.calls}.out"
