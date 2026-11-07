"""Register, check, re-link and adopt projects (SP2 spec §2, items 5-7)."""

import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from kengash_ai import gitops
from kengash_ai.model import (
    Event,
    KengashError,
    NeedsSetup,
    Plan,
    ProjectEntry,
    Ticket,
    UserError,
    utc_now,
)
from kengash_ai.ops import hygiene, jobs, leases, lifecycle, providers, records, skills, waiting
from kengash_ai.ops.records import repo_root, worktree_owner
from kengash_ai.store import documents, links, migrate, runtime, seed, storegit
from kengash_ai.store.locks import locked
from kengash_ai.store.paths import ProjectPaths, StorePaths
from kengash_ai.store.registry import (
    load_registry,
    save_registry,
    slug_for_path,
    slugify,
    unique_slug,
)
from kengash_ai.store.seed import ensure_project, ensure_store

SCAN_DEPTH = 3
SCAN_SKIP = frozenset(
    {".git", ".venv", "node_modules", "__pycache__", links.LINK, links.LEGACY_LINK}
)
NOT_GIT = "not a git repository: ticket worktrees will need git"


@dataclass
class InitResult:
    slug: str
    repo: Path
    link_target: Path
    created: bool
    warnings: list[str] = field(default_factory=list)

    @property
    def link(self) -> Path:
        """The repo's folder link, `<repo>/.kengash`."""
        return self.repo / links.LINK


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
    notes: list[Problem] = field(default_factory=list)  # SP12: worth knowing, not problems


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
    worktree = _worktree_of(paths, repo)
    if worktree is not None:  # a worktree of a registered repo: no second project (SP14)
        owner, main = worktree
        note = f"{repo} is a worktree of {owner}; kengash uses {owner} here"
        return InitResult(owner, main, paths.project(owner).root, False, [note])
    _refuse_obstruction(repo)
    ensure_store(paths)
    slug, created = _register(paths, repo)
    project = ensure_project(paths, slug)
    warnings = _attach(repo, project)
    if created:  # a new project gets its detected test and lint commands and a checks step
        hygiene.apply_checks(paths, slug, *hygiene.detect_commands(repo))
    storegit.commit_store(paths, f"kengash: init {slug}")
    return InitResult(slug, repo, project.root, created, warnings)


@dataclass
class Forgotten:
    """A project kengash forgot (or would forget, as a preview) (SP14 spec §2.2)."""

    slug: str
    path: Path
    plans: int
    tickets: int
    worktrees: int
    link: bool  # the repo's `.kengash` link pointed at its store folder and was removed
    dirty: int = 0  # worktrees holding uncommitted changes: those are lost, not kept


def forget_preview(slug: str, paths: StorePaths | None = None) -> Forgotten:
    """What `forget_project` would remove; nothing changes."""
    paths = paths or StorePaths.default()
    entry = load_registry(paths).projects.get(slug)
    if entry is None:
        raise UserError(f"unknown project: {slug}")
    project = paths.project(slug)
    plans = len(list(project.plans.glob("*.md"))) if project.plans.is_dir() else 0
    tickets = len(_ticket_ids(project))
    worktrees = _worktrees(paths, slug)
    dirty = sum(bool(_changed(worktree)) for worktree in worktrees)
    link = _our_link(entry.path, project)
    return Forgotten(slug, entry.path, plans, tickets, len(worktrees), link, dirty)


def _changed(worktree: Path) -> list[str]:
    try:
        return gitops.changed_files(worktree)
    except (OSError, subprocess.SubprocessError, KengashError):
        return []


def forget_project(slug: str, *, by: str, paths: StorePaths | None = None) -> Forgotten:
    """Remove a project from kengash: its registry entry, store folder, ticket worktrees and
    states, and its repo's `.kengash` link; refused while a worker or a loop of its runs.
    The store commit keeps every removed file in the store's git history."""
    paths = paths or StorePaths.default()
    preview = forget_preview(slug, paths)
    _refuse_running(paths, slug)
    project = paths.project(slug)
    ids = _ticket_ids(project)
    # first commit whatever the store holds, so its history keeps every file removed below
    storegit.commit_store(paths, f"kengash: before forgetting {slug}")
    with locked(paths.locks / "registry.lock"):
        registry = load_registry(paths)
        registry.projects.pop(slug, None)
        save_registry(paths, registry)
    repo = preview.path
    for worktree in _worktrees(paths, slug):
        if repo.is_dir():
            subprocess.run(
                ["git", "-C", str(repo), "worktree", "remove", "--force", str(worktree)],
                capture_output=True,
                check=False,
            )
            branch = f"kg/{worktree.name.split('-', 1)[-1]}"
            subprocess.run(
                ["git", "-C", str(repo), "branch", "-D", branch], capture_output=True, check=False
            )
        shutil.rmtree(worktree, ignore_errors=True)
    shutil.rmtree(paths.worktrees / slug, ignore_errors=True)
    if repo.is_dir():
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "prune"], capture_output=True, check=False
        )
    if preview.link:
        (repo / links.LINK).unlink()
    for ticket_id in ids:
        runtime.drop_ticket_state(paths, ticket_id)
    shutil.rmtree(project.root, ignore_errors=True)
    event = Event.model_validate(
        {
            "type": "project.forgotten",
            "project": slug,
            "plans": preview.plans,
            "tickets": preview.tickets,
            "by": by,
        }
    )
    records.record(paths, f"kengash: forget {slug}", event)
    return preview


def _ticket_ids(project: ProjectPaths) -> list[str]:
    tasks = project.root / "tasks"
    return sorted(path.stem for path in tasks.rglob("*.md")) if tasks.is_dir() else []


def _worktrees(paths: StorePaths, slug: str) -> list[Path]:
    folder = paths.worktrees / slug
    return sorted(path for path in folder.iterdir() if path.is_dir()) if folder.is_dir() else []


def _our_link(repo: Path, project: ProjectPaths) -> bool:
    link = repo / links.LINK
    return link.is_symlink() and link.resolve() == project.root.resolve()


def _refuse_running(paths: StorePaths, slug: str) -> None:
    for record in runtime.load_workers(paths):
        if record.project == slug and lifecycle.pid_alive(record.pid):
            raise UserError(f"a worker runs {record.id} in {slug}; stop it first")
    if any(lease.project == slug for lease in leases.live(paths)):
        raise UserError(f"a loop runs on {slug}; release or stop it first")


def relink(slug: str, new_path: Path, paths: StorePaths | None = None) -> InitResult:
    """Point a moved project's registry entry and `.kengash` link at its new place."""
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
    storegit.commit_store(paths, f"kengash: link {slug}")
    return InitResult(slug, repo, project.root, False, warnings)


def migrate_home() -> str | None:
    """Move a 0.1.0 store (~/.harness) to ~/.kengash once, leaving a link; the note to
    show, or None (SP8 spec decision 2)."""
    return migrate.legacy_home()


def doctor(
    fix: bool = False, scan: Path | None = None, paths: StorePaths | None = None
) -> DoctorReport:
    """Check every project's repo, link, exclude entry, documents and trust, then providers."""
    paths = paths or StorePaths.default()
    if not paths.home.is_dir():
        return DoctorReport(0, [Problem(f"no store at {paths.home}; run: kengash init")])
    registry = load_registry(paths)
    problems: list[Problem] = []
    for slug, entry in sorted(registry.projects.items()):
        problems += _check_project(paths, slug, entry.path, fix)
        notice = providers.trust_notice(paths, slug, entry.path) if entry.path.is_dir() else None
        if notice is not None:
            problems.append(Problem(notice, slug, warning=True))
    copies: dict[Path, list[str]] = {}
    for copy in skills.ignored_copies(paths):
        copies.setdefault(copy.parent, []).append(copy.name)
    for folder, names in copies.items():
        listed = f"built-in skill copies in {folder} ({', '.join(names)})"
        if fix:  # the store is a git repo: its history keeps what this removes
            for name in names:
                shutil.rmtree(folder / name)
            removed = f"removed ignored {listed}; the store's git history keeps them"
            problems.append(Problem(removed, fixed=True))
        else:
            hint = (
                "built-in skills are fixed; copy the agent to change one, "
                "or run: kengash doctor --fix"
            )
            problems.append(Problem(f"ignored {listed}: {hint}", warning=True))
    if fix and copies:
        storegit.commit_store(paths, "kengash: doctor removes ignored built-in skill copies")
    repos = [entry.path for _, entry in sorted(registry.projects.items()) if entry.path.is_dir()]
    home = skills.home_folder()
    for root in [*repos, home]:
        scope = " --global" if root == home else ""
        for folder, agent in skills.old_installs([root]):
            hint = f"run: kengash skills install --agent {agent}{scope}"
            message = f"old kengash skill names installed in {folder}; {hint}"
            problems.append(Problem(message, warning=True))
    if scan is not None:
        known = {entry.path.resolve() for entry in registry.projects.values()}
        for found in real_folders(scan.resolve(), SCAN_DEPTH):
            if found.parent not in known:
                problems.append(
                    Problem(f"unmanaged store {found}; run: kengash adopt {found.parent}")
                )
    if fix:
        jobs.prune_logs(paths, jobs.keep_days(paths))
    dead = waiting.dead_workers(paths)
    if fix and dead:
        waiting.check_workers(paths)
    for record in dead:
        done = "marked failed" if record.job == "ticket" else "dropped"
        hint = done if fix else "run: kengash doctor --fix"
        problems.append(Problem(f"worker of {record.id} died; {hint}", record.project, fix))
    problems += [
        Problem(check.message, warning=not check.blocking)
        for check in providers.check_providers(paths)
    ]
    clash = providers.cli_clash()
    if clash is not None:
        problems.append(Problem(clash, warning=True))
    checked = hygiene.checks(paths, fix=fix)  # each message names its scope
    problems += [Problem(n.message, None, n.fixed, n.warning) for n in checked if not n.info]
    notes = [Problem(n.message, None, n.fixed, False) for n in checked if n.info]
    return DoctorReport(len(registry.projects), problems, notes)


def adopt(path: Path, paths: StorePaths | None = None) -> AdoptResult:
    """Merge a project's real `.kengash/` (or 0.1.0 `.harness/`) folder into the store,
    archive it, and link."""
    paths = paths or StorePaths.default()
    repo = repo_root(path)
    found = links.real_folder(repo)
    if found is None:
        raise UserError(f"nothing to adopt: {repo / links.LINK} is not a real folder")
    source = found
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
    storegit.commit_store(paths, f"kengash: adopt {slug}")
    return AdoptResult(slug, added, conflicts, archive)


def _refuse_obstruction(repo: Path) -> None:
    real = links.real_folder(repo)
    if real is not None:
        raise NeedsSetup(f"{real} is a real folder; run: kengash adopt {repo}")
    if links.obstruction(repo) is links.LinkState.blocked:
        raise UserError(f"{repo / links.LINK} is a file; move it away first")


def _worktree_of(paths: StorePaths, repo: Path) -> tuple[str, Path] | None:
    """The registered project and repo that `repo` is a linked worktree of, else None."""
    if not paths.registry.exists():
        return None
    registry = load_registry(paths)
    if slug_for_path(registry, repo) is not None:
        return None
    owner = worktree_owner(registry, repo)
    return (owner, registry.projects[owner].path) if owner is not None else None


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
    legacy = links.legacy_link(repo, project.root)
    if legacy is not None:
        legacy.unlink()  # the 0.1.0 name of this same link
    return [] if links.ensure_excluded(repo) else [NOT_GIT]


def _check_project(paths: StorePaths, slug: str, repo: Path, fix: bool) -> list[Problem]:
    if not repo.is_dir():
        return [
            Problem(
                f"repo missing at {repo}; if it moved: kengash link {slug} <new-path>; "
                f"if it is gone for good: kengash forget {slug}",
                slug,
            )
        ]
    project = paths.project(slug)
    problems: list[Problem] = []
    state = links.link_state(repo, project.root)
    legacy = links.legacy_link(repo, project.root)
    real = links.real_folder(repo)
    if real is not None:
        problems.append(Problem(f"{real} is a real folder; run: kengash adopt {repo}", slug))
    elif state is links.LinkState.blocked:
        message = f"{repo / links.LINK} is a file; move it away, then: kengash doctor --fix"
        problems.append(Problem(message, slug))
    elif state is not links.LinkState.ok:
        if fix:
            links.make_link(repo, project.root)
        if legacy is None or state is not links.LinkState.missing:
            problems.append(_fixable(f"link {state.value}", slug, fix))
    if legacy is not None:  # 0.1.0's name for this link (SP8 spec decision 3)
        if fix:
            legacy.unlink()
        problems.append(_fixable(f"legacy .harness link: {links.LINK} replaces it", slug, fix))
    if links.is_excluded(repo) is False:
        if fix:
            links.ensure_excluded(repo)
        problems.append(_fixable(".kengash missing from .git/info/exclude", slug, fix))
    memory = links.state_of(project.memory_link, paths.memory)
    if memory in (links.LinkState.real_dir, links.LinkState.blocked):
        where = project.memory_link.relative_to(paths.home)
        kind = "folder" if memory is links.LinkState.real_dir else "file"
        message = (
            f"{where} is a real {kind}: move what it holds into {paths.memory} "
            "(kengash memory add), remove it, then run: kengash doctor --fix"
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
    hint = "repaired" if fixed else "run: kengash doctor --fix"
    return Problem(f"{message}; {hint}", slug, fixed)


def real_folders(root: Path, depth: int) -> list[Path]:
    """Real `.kengash/` (or 0.1.0 `.harness/`) folders at most `depth` levels below `root`."""
    found: list[Path] = []
    pending = [(root, 0)]
    while pending:
        directory, level = pending.pop()
        candidate = links.real_folder(directory)
        if candidate is not None:
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
