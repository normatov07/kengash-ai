"""A finishing worker starts what is now runnable (SP17 spec §3.4).

The same `compute` and `run_tickets` a conductor uses, called once as each ticket's worker
ends: no process stays behind, so there is still no daemon. It runs only after a loop was
asked for, and decisions (gates, failed tickets) stay with the conductor and the user.
"""

import contextlib
import traceback
from datetime import timedelta
from pathlib import Path

from kengash_ai import settings, workflow
from kengash_ai.model import KengashError, UserError, utc_now
from kengash_ai.ops import controls, leases, merging, queue, records
from kengash_ai.store import runtime
from kengash_ai.store.locks import locked
from kengash_ai.store.paths import StorePaths
from kengash_ai.store.registry import load_registry

ALL = "all"
AUTO_RETRIES = 2  # restarts of a failed ticket in Auto mode (SP21 spec §3)
RETRY_AFTER = timedelta(minutes=10)
MAX_IDLE = timedelta(hours=24)  # a loop that started nothing for this long is over


def note_claim(paths: StorePaths, project: str | None) -> None:
    """A loop now covers `project` (None: every project)."""
    scope = project or ALL
    with locked(_lock(paths)):
        intent = runtime.load_relay(paths)
        if scope not in intent.scopes:
            intent.scopes.append(scope)
        intent.touched = utc_now()
        runtime.save_relay(paths, intent)


def note_release(paths: StorePaths, project: str | None) -> None:
    """The loop over `project` ended."""
    _drop(paths, project or ALL)


def advance(paths: StorePaths) -> list[str]:
    """Start every ticket a loop covers that can start now; the ids that started. A scope
    with nothing runnable, running, held back or at a gate is finished and forgotten."""
    intent = runtime.load_relay(paths)
    if intent.scopes and utc_now() - intent.touched > MAX_IDLE:
        _keep(paths, [])
        intent.scopes = []
    # a loop claimed before the relay existed, or whose conductor has gone quiet, still counts
    leased = [lease.project or ALL for lease in leases.live(paths)]
    started: list[str] = []
    for scope in dict.fromkeys([*intent.scopes, *leased]):
        with contextlib.suppress(KengashError):  # a removed project is handled just below
            _recover(paths, None if scope == ALL else scope)
        project = None if scope == ALL else scope
        try:
            found = queue.compute(paths, project)
        except (
            UserError
        ):  # a bad SETTINGS.md is fixed and the loop goes on; a removed project is not
            if project is not None and project not in load_registry(paths).projects:
                _drop(paths, scope)
            continue
        ids = [ticket.id for ticket in found.runnable if _relays(paths, ticket.project)]
        if ids:
            result = controls.run_tickets(ids, project=None, by="relay")
            started += [one.id for one in result.started]
        elif not (
            found.runnable
            or found.running
            or found.gates
            or found.held_back
            or found.paused
            or found.blocked
        ):
            _drop(paths, scope)
    if started:
        _touch(paths)
    return started


def _recover(paths: StorePaths, project: str | None) -> None:
    """Auto mode: restart failed tickets a few times and retry merges that could not finish,
    each once it has been quiet for RETRY_AFTER (SP21 spec §3)."""
    for slug in records.scope(paths, project):
        resolved = settings.load(paths, slug)
        if resolved.loop_start != "auto":
            continue
        for doc in records.project_tickets(paths, slug).values():
            ticket = doc.meta
            if utc_now() - ticket.updated < RETRY_AFTER:
                continue
            if ticket.status == workflow.FAILED:
                _retry(paths, ticket.id)
            elif ticket.status == workflow.AWAITING_MERGE and resolved.merge.mode == "auto":
                with contextlib.suppress(KengashError):
                    merging.merge_if_clean(paths, slug, ticket.id, by="relay")


def _retry(paths: StorePaths, ticket_id: str) -> None:
    state = runtime.load_ticket_state(paths, ticket_id)
    if state.auto_retries >= AUTO_RETRIES:
        return
    state.auto_retries += 1
    runtime.save_ticket_state(paths, ticket_id, state)
    with contextlib.suppress(KengashError):
        controls.run_tickets([ticket_id], project=None, by="relay")


def covered(paths: StorePaths) -> list[str]:
    """What the relay would still act for."""
    return list(runtime.load_relay(paths).scopes)


def forget_unleased(paths: StorePaths) -> None:
    """Drop the scopes no live loop holds: `loop release` by a conductor whose lease is gone."""
    held = {lease.project or ALL for lease in leases.live(paths)}
    _keep(paths, [scope for scope in runtime.load_relay(paths).scopes if scope in held])


def advance_quietly(paths: StorePaths | None = None) -> list[str]:
    """`advance` for a worker that is ending: its failure must not fail the ticket."""
    try:
        return advance(paths or StorePaths.default())
    except Exception:  # whatever went wrong here, the ticket itself is finished
        traceback.print_exc()
        return []


def _relays(paths: StorePaths, slug: str) -> bool:
    try:
        return settings.load(paths, slug).loop_relay
    except UserError:
        return False


def _drop(paths: StorePaths, scope: str) -> None:
    with locked(_lock(paths)):
        intent = runtime.load_relay(paths)
        if scope in intent.scopes:
            intent.scopes.remove(scope)
            runtime.save_relay(paths, intent)


def _keep(paths: StorePaths, scopes: list[str]) -> None:
    with locked(_lock(paths)):
        intent = runtime.load_relay(paths)
        intent.scopes = [scope for scope in intent.scopes if scope in scopes]
        runtime.save_relay(paths, intent)


def _touch(paths: StorePaths) -> None:
    with locked(_lock(paths)):
        intent = runtime.load_relay(paths)
        intent.touched = utc_now()
        runtime.save_relay(paths, intent)


def _lock(paths: StorePaths) -> Path:
    return paths.locks / "relay.lock"
