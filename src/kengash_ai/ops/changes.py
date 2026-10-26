"""What a ticket changed, and how to open its sessions (SP3 spec §10)."""

import shlex
from dataclasses import dataclass, field

from kengash_ai import adapters, gitops, settings
from kengash_ai.model import STEP_ROLES, Doc, HarnessError, Ticket, UserError
from kengash_ai.ops import records
from kengash_ai.store import documents
from kengash_ai.store.paths import StorePaths
from kengash_ai.store.registry import load_registry


@dataclass
class Change:
    path: str
    added: int | None
    removed: int | None
    loop: str
    step: str
    model: str
    commit: str


@dataclass
class Changes:
    id: str
    project: str
    ref: str
    changes: list[Change] = field(default_factory=list)
    diff: str = ""


@dataclass
class Attach:
    id: str
    project: str
    role: str
    command: str


def ticket_changes(ticket_id: str, *, diff: bool, project: str | None) -> Changes:
    """Per file and commit: what the ticket changed, at which loop and step, by which model.
    Reads the ticket branch, or the base branch once the branch is merged and gone."""
    paths = StorePaths.default()
    slug, doc = _ticket(paths, ticket_id, project)
    entry = load_registry(paths).projects[slug]
    branch = doc.meta.branch or f"hrn/{ticket_id}"
    ref = branch if gitops.branch_exists(entry.path, branch) else entry.base
    commits = gitops.ticket_commits(entry.path, str(doc.meta.uuid), ref)
    if not commits:
        raise UserError(f"{ticket_id} has no commits yet")
    found = Changes(ticket_id, slug, ref)
    for commit in commits:
        trailers = commit.trailers
        found.changes += [
            Change(
                change.path,
                change.added,
                change.removed,
                trailers.get("Harness-Loop", "?"),
                trailers.get("Harness-Step", "?"),
                trailers.get("Harness-Model", "?"),
                commit.sha,
            )
            for change in commit.files
        ]
    if diff:
        found.diff = "\n".join(gitops.show(entry.path, commit.sha) for commit in commits)
    return found


def attach_command(ticket_id: str, *, role: str | None, project: str | None) -> Attach:
    """The command that opens a role's session in the ticket's worktree."""
    paths = StorePaths.default()
    slug, doc = _ticket(paths, ticket_id, project)
    sessions = doc.meta.sessions
    if role is None:
        try:
            current = settings.load(paths, slug).role_of(doc.meta.step or "")
        except HarnessError:  # broken settings: the built-in steps still name their roles
            current = STEP_ROLES.get(doc.meta.step or "")
        role = current if current in sessions else next(reversed(sessions), None)
        if role is None:
            raise UserError(f"{ticket_id} has no sessions")
    session = sessions.get(role)
    if session is None:
        raise UserError(f"{ticket_id} has no {role} session")
    worktree = paths.worktree(slug, ticket_id)
    folder = worktree if worktree.is_dir() else load_registry(paths).projects[slug].path
    argv = adapters.get(session.provider, runtime=paths.runtime).attach_command(session.id)
    return Attach(ticket_id, slug, role, f"cd {shlex.quote(str(folder))} && {shlex.join(argv)}")


def _ticket(paths: StorePaths, ticket_id: str, project: str | None) -> tuple[str, Doc[Ticket]]:
    slug, path = records.locate_ticket(paths, ticket_id, project)
    return slug, documents.load_ticket(path)
