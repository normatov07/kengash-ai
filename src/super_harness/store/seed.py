"""Create the store and project folders, seeding default files once (system spec §4.1)."""

from importlib import resources
from pathlib import Path

from super_harness.model import Folder
from super_harness.store import links, storegit
from super_harness.store.paths import ProjectPaths, StorePaths

_PACKAGE_DEFAULTS = resources.files("super_harness.store") / "defaults"
_PACKAGE_ROLES = resources.files("super_harness") / "roles"


def package_default(name: str) -> str:
    """Text of a default file shipped inside the package."""
    return (_PACKAGE_DEFAULTS / name).read_text(encoding="utf-8")


def _seed(name: str, target: Path) -> None:
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(package_default(name), encoding="utf-8")


def ensure_store(paths: StorePaths) -> None:
    """Create the store layout and its git repo; existing files are never touched."""
    for directory in (paths.memory, paths.defaults, paths.projects, paths.journal, paths.locks):
        directory.mkdir(parents=True, exist_ok=True)
    paths.home.chmod(0o700)
    _seed("MEMORY.md", paths.memory / "MEMORY.md")
    _seed("DECISIONS.md", paths.memory / "DECISIONS.md")
    _seed("SETTINGS.md", paths.defaults / "SETTINGS.md")
    _seed("PROCESS.md", paths.defaults / "PROCESS.md")
    _seed_roles(paths.defaults / "roles")
    storegit.ensure_repo(paths.home)


def ensure_project(paths: StorePaths, slug: str) -> ProjectPaths:
    """Create a project's folders and memory link; copy SETTINGS.md and PROCESS.md if missing."""
    project = paths.project(slug)
    project.plans.mkdir(parents=True, exist_ok=True)
    for folder in Folder:
        project.folder(folder).mkdir(parents=True, exist_ok=True)
    link_memory(paths, project)
    for target in (project.settings, project.process):
        if not target.exists():
            source = paths.defaults / target.name
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return project


def link_memory(paths: StorePaths, project: ProjectPaths) -> bool:
    """Point the project's `memory` at the store's (`../../memory`), replacing a missing or
    stale link; False when a real file or folder sits there (never replaced)."""
    link = project.memory_link
    if links.state_of(link, paths.memory) is links.LinkState.ok:
        return True
    if link.exists() and not link.is_symlink():
        return False
    if link.is_symlink():
        link.unlink()
    link.symlink_to(Path("..") / ".." / "memory", target_is_directory=True)
    return True


def _seed_roles(target: Path) -> None:
    """Copy each package role skill whose folder is missing; edited ones stay as they are."""
    for role in _PACKAGE_ROLES.iterdir():
        if not role.is_dir() or (target / role.name).exists():
            continue
        folder = target / role.name
        folder.mkdir(parents=True)
        for item in role.iterdir():
            if item.is_file():
                (folder / item.name).write_bytes(item.read_bytes())
