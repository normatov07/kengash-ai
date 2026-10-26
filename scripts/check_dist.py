"""Check built artifacts: the wheel and sdist hold the product and nothing local (SP7 spec
decision 8). Usage: `uv run python scripts/check_dist.py dist/`; prints one line per problem."""

import sys
import tarfile
import zipfile
from pathlib import Path

WHEEL_NEEDS = (
    "super_harness/__init__.py",
    "super_harness/ui/static/fonts/",
    "super_harness/ui/static/index.html",
    "super_harness/skills/",
    "super_harness/roles/",
    "super_harness/store/defaults/SETTINGS.md",
)
SDIST_NEEDS = ("src/super_harness/__init__.py", "skills/", "LICENSE", "pyproject.toml")
# local agent, tool and editor folders, and the original request: never part of a release
FORBIDDEN = (
    ".claude/",
    ".superpowers/",
    ".import_linter_cache/",
    ".venv/",
    ".mypy_cache/",
    ".pytest_cache/",
    ".ruff_cache/",
    "__pycache__/",
    "full prompt of app.md",
    "untitled.md",
)


def main(argv: list[str]) -> int:
    folder = Path(argv[0]) if argv else Path("dist")
    problems: list[str] = []
    wheels, sdists = sorted(folder.glob("*.whl")), sorted(folder.glob("*.tar.gz"))
    if not wheels:
        problems.append(f"{folder}: no wheel")
    if not sdists:
        problems.append(f"{folder}: no sdist")
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as archive:
            problems += _check("wheel", archive.namelist(), WHEEL_NEEDS)
    for sdist in sdists:
        with tarfile.open(sdist) as archive:
            # drop the archive's top folder, `super_harness-<version>/`
            names = [name.partition("/")[2] for name in archive.getnames()]
            problems += _check("sdist", names, SDIST_NEEDS)
    for problem in problems:
        print(problem)
    return 1 if problems else 0


def _check(kind: str, names: list[str], needs: tuple[str, ...]) -> list[str]:
    found = [f"{kind} lacks {need}" for need in needs if not _has(names, need)]
    for bad in FORBIDDEN:
        if any(_under(name, bad) for name in names):
            found.append(f"{kind} ships {bad}")
    return found


def _has(names: list[str], need: str) -> bool:
    return any(name.startswith(need) for name in names) if need.endswith("/") else need in names


def _under(name: str, bad: str) -> bool:
    if bad.endswith("/"):
        return name.startswith(bad) or f"/{bad}" in name
    return name == bad or name.endswith(f"/{bad}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
