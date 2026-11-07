"""Settings, memory and context for the current project (SP2 spec §3)."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from kengash_ai import memory, settings
from kengash_ai.model import Folder, NeedsSetup, Settings, UserError
from kengash_ai.ops import compaction
from kengash_ai.ops.records import repo_root, worktree_owner
from kengash_ai.store import documents
from kengash_ai.store.paths import StorePaths
from kengash_ai.store.registry import load_registry
from kengash_ai.store.yamlio import dump_yaml

GATES = ("needs_approval", "stalled", "failed", "awaiting_merge")


@dataclass
class OpenGate:
    id: str
    sub_status: str
    title: str


@dataclass
class Context:
    memory: str
    project: str | None = None
    process: list[str] = field(default_factory=list)
    gates: list[OpenGate] = field(default_factory=list)


def resolve_slug(project: str | None, cwd: Path, paths: StorePaths | None = None) -> str | None:
    """The named project, else the registered project containing `cwd`, else None."""
    paths = paths or StorePaths.default()
    registry = load_registry(paths)
    if project is not None:
        if project not in registry.projects:
            raise UserError(f"unknown project: {project}")
        return project
    here = repo_root(cwd)
    for slug, entry in registry.projects.items():
        if here == entry.path or entry.path in here.parents:
            return slug
    return worktree_owner(registry, here)


def project_slug(value: str, cwd: Path, paths: StorePaths | None = None) -> str:
    """A `--project` value as a slug (SP9 spec decision 1): a registered slug as is, else a
    folder inside a registered repo, the deepest repo when registered repos nest."""
    paths = paths or StorePaths.default()
    registry = load_registry(paths)
    if value in registry.projects:
        return value
    folder = (cwd / Path(value).expanduser()).resolve()
    if not folder.is_dir():
        raise UserError(f"unknown project: {value}")
    holders = [
        (len(entry.path.parts), slug)
        for slug, entry in registry.projects.items()
        if folder == entry.path or entry.path in folder.parents
    ]
    if holders:
        return max(holders)[1]
    owner = worktree_owner(registry, folder)
    if owner is None:
        raise NeedsSetup(f"not a kengash project: {folder}; run: kengash init {folder}")
    return owner


def settings_for(project: str | None, cwd: Path) -> Settings:
    paths = StorePaths.default()
    return settings.load(paths, resolve_slug(project, cwd, paths))


def settings_yaml(project: str | None, cwd: Path) -> str:
    return dump_yaml(settings_for(project, cwd).model_dump(mode="json"))


def setting(key: str, project: str | None, cwd: Path) -> Any:
    return settings.get(settings_for(project, cwd), key)


def settings_problems(project: str | None, cwd: Path) -> list[str]:
    paths = StorePaths.default()
    return settings.problems(paths, resolve_slug(project, cwd, paths))


def remember(
    text: str,
    why: str,
    *,
    section: str,
    decision: bool,
    rejected: str | None,
    project: str | None,
    cwd: Path,
    by: str,
) -> memory.AddResult:
    """Add a memory line; MEMORY.md past its cap starts a compaction in the background."""
    paths = StorePaths.default()
    slug = resolve_slug(project, cwd, paths)
    result = memory.add(
        paths, text, why, section=section, decision=decision, rejected=rejected, project=slug, by=by
    )
    if result.added and result.file == "MEMORY.md" and result.over_cap:
        result.compacting = compaction.start_background(paths)
    return result


def recall(decisions: bool, project: str | None, cwd: Path) -> str:
    paths = StorePaths.default()
    return memory.show(paths, decisions=decisions, project=resolve_slug(project, cwd, paths))


def open_gates(paths: StorePaths, slug: str) -> list[OpenGate]:
    """In-process tickets waiting for the conductor or the user."""
    gates: list[OpenGate] = []
    for path in sorted(paths.project(slug).folder(Folder.in_process).glob("*.md")):
        try:
            ticket = documents.load_ticket(path).meta
        except (UserError, ValidationError):
            continue
        sub_status = ticket.status.split("/", 1)[1]
        if sub_status in GATES:
            gates.append(OpenGate(ticket.id, sub_status, ticket.title))
    return gates


def context(project: str | None, cwd: Path) -> Context:
    """MEMORY.md, plus the project's PROCESS.md headings and open gates when there is one."""
    paths = StorePaths.default()
    digest = Context(memory.show(paths))
    slug = resolve_slug(project, cwd, paths)
    if slug is not None:
        process = paths.project(slug).process
        lines = process.read_text(encoding="utf-8").splitlines() if process.exists() else []
        digest.project = slug
        digest.process = [line for line in lines if line.startswith("#")]
        digest.gates = open_gates(paths, slug)
    return digest
