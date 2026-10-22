"""Fail when agent-facing Markdown files exceed their line caps.

Entry files are routers and topic docs stay small (docs/conventions/instruction-files.md).
Specs and plans under docs/superpowers/ are exempt. Prints nothing when every file fits.
"""

import sys
from pathlib import Path

CAPS: tuple[tuple[str, int], ...] = (
    ("AGENTS.md", 100),
    ("docs/**/*.md", 150),
)
EXEMPT_PREFIX = "docs/superpowers/"


def violations(root: Path) -> list[str]:
    """Return one line per file over its cap, as 'path: N lines > cap M'."""
    found: list[str] = []
    for pattern, cap in CAPS:
        for path in sorted(root.glob(pattern)):
            rel = path.relative_to(root).as_posix()
            if rel.startswith(EXEMPT_PREFIX):
                continue
            lines = len(path.read_text(encoding="utf-8").splitlines())
            if lines > cap:
                found.append(f"{rel}: {lines} lines > cap {cap}")
    return found


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0]) if args else Path.cwd()
    found = violations(root)
    for line in found:
        print(line)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
