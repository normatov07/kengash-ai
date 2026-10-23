"""Register, check, re-link and adopt projects (SP2 spec §2, items 5-7)."""

import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from super_harness.model import NeedsSetup, Plan, ProjectEntry, Ticket, UserError, utc_now
from super_harness.ops import providers, waiting
from super_harness.ops.records import repo_root
from super_harness.store import documents, links, seed, storegit
from super_harness.store.locks import locked
from super_harness.store.paths import ProjectPaths, StorePaths
from super_harness.store.registry import (
    load_registry,
    save_registry,
    slug_for_path,
    slugify,
    unique_slug,
)
from super_harness.store.seed import ensure_project, ensure_store

SCAN_DEPTH = 3
SCAN_SKIP = frozenset({".git", ".venv", "node_modules", "__pycache__", links.LINK})
NOT_GIT = "not a git repository: ticket worktrees will need git"


@dataclass
class InitResult:
    slug: str
    repo: Path
    link_target: Path
    created: bool
    warnings: list[str] = field(default_factory=list)


@dataclass
class Problem:
    message: str
    slug: str | None = None
    fixed: bool = False
    warning: bool = False


@dataclass
class DoctorReport:
    projects: int
    problems: list[Problem]


@dataclass
class AdoptResult:
    slug: str
    added: int
    conflicts: int
    archive: Path


def init_project(path: Path, paths: StorePaths | None = None) -> InitResult:
    """Register the project containing `path` and link it to the store (idempotent)."""
    paths = paths or StorePaths.default()
    repo = repo_root(path)
    _refuse_obstruction(repo)
    ensure_store(paths)
    slug, created = _register(paths, repo)
    project = ensure_project(paths, slug)
    warnings = _attach(repo, project)
    storegit.commit_store(paths, f"harness: init {slug}")
    return InitResult(slug, repo, project.root, created, warnings)


def relink(slug: str, new_path: Path, paths: StorePaths | None = None) -> InitResult:
    """Point a moved project's registry entry and `.harness` link at its new place."""
    paths = paths or StorePaths.default()
    repo = repo_root(new_path)
    _refuse_obstruction(repo)
    with locked(paths.locks / "registry.lock"):
        registry = load_registry(paths)
        entry = registry.projects.get(slug)
        if entry is None:
            raise UserError(f"unknown project: {slug}")
        owner = slug_for_path(registry, repo)
        if owner not in (None, slug):
            raise UserError(f"{repo} is already registered as {owner}")
        entry.path = repo
        save_registry(paths, registry)
    project = ensure_project(paths, slug)
    warnings = _attach(repo, project)
    storegit.commit_store(paths, f"harness: link {slug}")
    return InitResult(slug, repo, project.root, False, warnings)


def doctor(
    fix: bool = False, scan: Path | None = None, paths: StorePaths | None = None
) -> DoctorReport:
    """Check every project's repo, link, exclude entry, documents and trust, then providers."""
    paths = paths or StorePaths.default()
    if not paths.home.is_dir():
        return DoctorReport(0, [Problem(f"no store at {paths.home}; run: harness init")])
    registry = load_registry(paths)
    problems: list[Problem] = []
    for slug, entry in sorted(registry.projects.items()):
        problems += _check_project(paths, slug, entry.path, fix)
        notice = providers.trust_notice(paths, slug, entry.path) if entry.path.is_dir() else None
        if notice is not None:
            problems.append(Problem(notice, slug, warning=True))
    if scan is not None:
        known = {entry.path.resolve() for entry in registry.projects.values()}
        for found in _real_folders(scan.resolve(), SCAN_DEPTH):
            if found.parent not in known:
                problems.append(
                    Problem(f"unmanaged store {found}; run: harness adopt {found.parent}")
                )
    dead = waiting.dead_workers(paths)
    if fix and dead:
        waiting.check_workers(paths)
    for record in dead:
        done = "marked failed" if record.job == "ticket" else "dropped"
        hint = done if fix else "run: harness doctor --fix"
        problems.append(Problem(f"worker of {record.id} died; {hint}", record.project, fix))
    problems += [
        Problem(check.message, warning=not check.blocking)
        for check in providers.check_providers(paths)
    ]
    clash = providers.cli_clash()
    if clash is not None:
        problems.append(Problem(clash, warning=True))
    return DoctorReport(len(registry.projects), problems)


def adopt(path: Path, paths: StorePaths | None = None) -> AdoptResult:
    """Merge a project's real `.harness/` folder into the store, archive it, and link."""
    paths = paths or StorePaths.default()
    repo = repo_root(path)
    source = repo / links.LINK
    if links.obstruction(repo) is not links.LinkState.real_dir:
        raise UserError(f"nothing to adopt: {source} is not a real folder")
    ensure_store(paths)
    slug, _ = _register(paths, repo)
    project = paths.project(slug)
    archive = project.archive / f"adopted-{utc_now():%Y%m%dT%H%M%SZ}"
    with locked(paths.locks / f"{slug}.lock"):
        project.root.mkdir(parents=True, exist_ok=True)
        for target in (project.settings, project.process):
            incoming = source / target.name
            if not target.exists() and incoming.is_file():
                shutil.copy2(incoming, target)
        ensure_project(paths, slug)
        added, conflicts = _merge(ProjectPaths(source), project, archive / "replaced")
        archive.mkdir(parents=True, exist_ok=True)
        shutil.move(source, archive / "original")
    _attach(repo, project)
    storegit.commit_store(paths, f"harness: adopt {slug}")
    return AdoptResult(slug, added, conflicts, archive)


def _refuse_obstruction(repo: Path) -> None:
    blocker = links.obstruction(repo)
    if blocker is links.LinkState.real_dir:
        raise NeedsSetup(f"{repo / links.LINK} is a real folder; run: harness adopt {repo}")
    if blocker is links.LinkState.blocked:
        raise UserError(f"{repo / links.LINK} is a file; move it away first")


def _register(paths: StorePaths, repo: Path) -> tuple[str, bool]:
    with locked(paths.locks / "registry.lock"):
        registry = load_registry(paths)
        slug = slug_for_path(registry, repo)
        if slug is not None:
            return slug, False
        slug = unique_slug(slugify(repo.name), registry.projects)
        registry.projects[slug] = ProjectEntry(path=repo, base=_branch(repo), added=date.today())
        save_registry(paths, registry)
        return slug, True


def _branch(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "symbolic-ref", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "main"


def _attach(repo: Path, project: ProjectPaths) -> list[str]:
    if links.link_state(repo, project.root) is not links.LinkState.ok:
        links.make_link(repo, project.root)
    return [] if links.ensure_excluded(repo) else [NOT_GIT]


def _check_project(paths: StorePaths, slug: str, repo: Path, fix: bool) -> list[Problem]:
    if not repo.is_dir():
        return [
            Problem(f"repo missing at {repo}; if it moved: harness link {slug} <new-path>", slug)
        ]
    project = paths.project(slug)
    problems: list[Problem] = []
    state = links.link_state(repo, project.root)
    if state is links.LinkState.real_dir:
        problems.append(
            Problem(f"{repo / links.LINK} is a real folder; run: harness adopt {repo}", slug)
        )
    elif state is links.LinkState.blocked:
        message = f"{repo / links.LINK} is a file; move it away, then: harness doctor --fix"
        problems.append(Problem(message, slug))
    elif state is not links.LinkState.ok:
        if fix:
            links.make_link(repo, project.root)
        problems.append(_fixable(f"link {state.value}", slug, fix))
    if links.is_excluded(repo) is False:
        if fix:
            links.ensure_excluded(repo)
        problems.append(_fixable(".harness missing from .git/info/exclude", slug, fix))
    memory = links.state_of(project.memory_link, paths.memory)
    if memory in (links.LinkState.real_dir, links.LinkState.blocked):
        where = project.memory_link.relative_to(paths.home)
        kind = "folder" if memory is links.LinkState.real_dir else "file"
        message = (
            f"{where} is a real {kind}: move what it holds into {paths.memory} "
            "(harness memory add), remove it, then run: harness doctor --fix"
        )
        problems.append(Problem(message, slug))
    elif memory is not links.LinkState.ok:
        if fix:
            seed.link_memory(paths, project)
        problems.append(_fixable(f"memory link {memory.value}", slug, fix))
    for path, kind in documents.iter_documents(project):
        problem = documents.check_document(path, kind)
        if problem is not None:
            problems.append(Problem(f"{path.relative_to(paths.home)}: {problem}", slug))
    return problems


def _fixable(message: str, slug: str, fixed: bool) -> Problem:
    hint = "repaired" if fixed else "run: harness doctor --fix"
    return Problem(f"{message}; {hint}", slug, fixed)


def _real_folders(root: Path, depth: int) -> list[Path]:
    """Real `.harness/` folders at most `depth` levels below `root`."""
    found: list[Path] = []
    pending = [(root, 0)]
    while pending:
        directory, level = pending.pop()
        candidate = directory / links.LINK
        if candidate.is_dir() and not candidate.is_symlink():
            found.append(candidate)
        if level == depth:
            continue
        try:
            children = [
                child
                for child in directory.iterdir()
                if child.is_dir() and not child.is_symlink() and child.name not in SCAN_SKIP
            ]
        except OSError:
            continue
        pending += [(child, level + 1) for child in children]
    return sorted(found)


def _valid_documents(
    project: ProjectPaths,
) -> Iterator[tuple[Path, Plan | Ticket, dict[str, str]]]:
    for path, kind in documents.iter_documents(project):
        try:
            meta, sections = documents.load_any(path, kind)
        except (UserError, ValidationError):
            continue
        yield path, meta, sections


def _merge(source: ProjectPaths, project: ProjectPaths, replaced: Path) -> tuple[int, int]:
    """Copy plans and tickets from `source`; on a uuid clash the newer `updated` wins."""
    by_uuid = {meta.uuid: (path, meta) for path, meta, _ in _valid_documents(project)}
    taken_ids = {meta.id: meta.uuid for _, meta in by_uuid.values()}
    added = conflicts = 0
    for _, meta, sections in _valid_documents(source):
        clash = by_uuid.get(meta.uuid)
        if clash is None:
            if taken_ids.get(meta.id, meta.uuid) != meta.uuid:
                conflicts += 1
                continue
            added += 1
        else:
            conflicts += 1
            current_path, current = clash
            if current.updated >= meta.updated:
                continue
            replaced.mkdir(parents=True, exist_ok=True)
            shutil.copy2(current_path, replaced / current_path.name)
            current_path.unlink()
        documents.save_any(project, meta, sections)
    return added, conflicts
