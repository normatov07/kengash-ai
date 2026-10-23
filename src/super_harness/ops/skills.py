"""Skills (SP4 spec decisions 2 to 7): role skills for worker prompts; lint and install of
the installed skills."""

from importlib import resources
from pathlib import Path

from super_harness.model import UserError
from super_harness.store.frontmatter import split_frontmatter
from super_harness.store.paths import StorePaths

ROLES = (
    "plan",
    "review-plan",
    "implement",
    "review-code",
    "review-security",
    "run-tests",
    "sync-docs",
)


def roles_dir() -> Path:
    """The package's role skills, `super_harness/roles/<role>/SKILL.md`."""
    return Path(str(resources.files("super_harness") / "roles"))


def role_text(paths: StorePaths, slug: str, skill: str) -> str | None:
    """The body of a role skill: the project's, else the defaults', else the package's."""
    for folder in (paths.project(slug).root / "roles", paths.defaults / "roles", roles_dir()):
        path = folder / skill / "SKILL.md"
        if path.is_file():
            try:
                return split_frontmatter(path.read_text(encoding="utf-8"))[1]
            except UserError:
                return path.read_text(encoding="utf-8")  # a hand-written file without frontmatter
    return None
