"""Create the store and project folders, seeding default files once (system spec §4.1)."""

from importlib import resources
from pathlib import Path

from super_harness.model import Folder
from super_harness.store import storegit
from super_harness.store.paths import ProjectPaths, StorePaths

_PACKAGE_DEFAULTS = resources.files("super_harness.store") / "defaults"


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
    storegit.ensure_repo(paths.home)


def ensure_project(paths: StorePaths, slug: str) -> ProjectPaths:
    """Create a project's folders and memory link; copy SETTINGS.md and PROCESS.md if missing."""
    project = paths.project(slug)
    project.plans.mkdir(parents=True, exist_ok=True)
    for folder in Folder:
        project.folder(folder).mkdir(parents=True, exist_ok=True)
    if not project.memory_link.is_symlink():
        project.memory_link.symlink_to(Path("..") / ".." / "memory", target_is_directory=True)
    for target in (project.settings, project.process):
        if not target.exists():
            source = paths.defaults / target.name
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return project
