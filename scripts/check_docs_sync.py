"""Fail when a package module changes without its docs/modules/<module>/README.md.

A module is a top-level package or .py file under src/kengash_ai/; package dunder
files and non-Python files at the top level are not modules. Prints nothing when in sync.
"""

import argparse
import subprocess
import sys

PACKAGE = "src/kengash_ai/"


def module_of(path: str) -> str | None:
    """Return the module a repo-relative path belongs to, or None."""
    if not path.startswith(PACKAGE):
        return None
    head, sep, _ = path.removeprefix(PACKAGE).partition("/")
    if sep:
        return head
    if head.startswith("__") or not head.endswith(".py"):
        return None
    return head.removesuffix(".py")


def problems(changed: list[str]) -> list[str]:
    """Return one line per changed module whose doc did not change too."""
    changed_set = set(changed)
    modules = sorted({module for path in changed if (module := module_of(path))})
    return [
        f"{module}: changed without docs/modules/{module}/README.md"
        for module in modules
        if f"docs/modules/{module}/README.md" not in changed_set
    ]


def changed_files(base: str | None, staged: bool) -> list[str]:
    """List paths changed in the index (staged) or in base...HEAD."""
    command = ["git", "diff", "--name-only"]
    command += ["--cached"] if staged else [f"{base}...HEAD"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(
            f"git diff failed: {result.stderr.strip()}; pass a valid --base, e.g. origin/main"
        )
    return result.stdout.splitlines()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check module docs change with their modules.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--base", help="compare BASE...HEAD")
    source.add_argument("--staged", action="store_true", help="compare staged changes")
    args = parser.parse_args(argv)
    found = problems(changed_files(args.base, args.staged))
    for line in found:
        print(line)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
