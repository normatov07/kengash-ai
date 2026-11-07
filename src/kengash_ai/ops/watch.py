"""Watching workers (SP13 spec §3): a viewer tab per worker and a dashboard per loop,
opened in the user's terminal; nothing here runs a model or fails its caller."""

import os
import shlex
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from kengash_ai import settings
from kengash_ai.model import KengashError, UserError
from kengash_ai.ops import changes, jobs, skills, terminals, viewers
from kengash_ai.store.paths import StorePaths

OFF = "KENGASH_WATCH"  # "off" turns every tab and notification off (tests, evals, CI)


def disabled(env: Mapping[str, str] | None = None) -> bool:
    """Tabs and notifications are off for this process."""
    value = (env if env is not None else os.environ).get(OFF, "")
    return value.strip().lower() in ("off", "0", "false", "no")


def cli_name() -> str:
    """How a tab reaches this CLI: `kengash` when it is first on PATH, else its path."""
    return skills.invoked_name(sys.argv[0])


def open_ticket(paths: StorePaths, slug: str, ticket_id: str) -> str:
    """Open the ticket's worker tab unless one is open; what the user watches it with."""
    command = [cli_name(), "logs", ticket_id, "--watch"]
    return _open(paths, slug, f"ticket-{ticket_id}", f"kg {ticket_id}", command)


def open_dashboard(paths: StorePaths, project: str | None) -> str:
    """Open the loop's dashboard tab unless one is open for this scope."""
    command = [cli_name(), "watch", *(["-p", project] if project else [])]
    title = f"kg watch {project}" if project else "kg watch"
    return _open(paths, project, f"watch-{project or 'all'}", title, command)


def attach_tab(ticket_id: str, *, role: str | None, project: str | None) -> str:
    """Open a tab on a role's own session in the ticket's worktree, so the user talks to
    that agent; refused while a worker drives the session (SP13 spec §3.6)."""
    paths = StorePaths.default()
    if jobs.alive(paths, ticket_id) is not None:
        raise UserError(f"a worker is running {ticket_id}; attach once it stops")
    found = changes.attach_command(ticket_id, role=role, project=project)
    title = f"kg {ticket_id} {found.role}"
    key = f"attach-{ticket_id}-{found.role}"
    return _open(paths, found.project, key, title, ["sh", "-c", found.command])


def _open(paths: StorePaths, slug: str | None, key: str, title: str, command: list[str]) -> str:
    printed = shlex.join(command)
    if disabled():
        return printed
    try:
        resolved = settings.load(paths, slug)
    except (KengashError, UserError):
        return printed
    if resolved.watch.tabs == "off":
        return printed
    terminal = terminals.detect(os.environ, resolved.watch.terminal)
    if terminal is None:
        return printed
    shown = f"{terminal.name} tab {title}"
    if not viewers.claim(paths, key):
        return shown  # its viewer runs, or its tab is opening
    if terminals.open_tab(terminal, title, command, cwd=Path.cwd()):
        return shown
    viewers.unclaim(paths, key)
    return printed


@contextmanager
def viewing(key: str) -> Iterator[None]:
    """This process is `key`'s viewer for the block, so no second tab opens for it."""
    paths = StorePaths.default()
    viewers.register(paths, key)
    try:
        yield
    finally:
        viewers.release(paths, key)
