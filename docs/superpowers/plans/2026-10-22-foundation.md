# Foundation (Sub-project 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the empty repo into a working Python project with a `harness --version` CLI, enforced doc conventions, agent instruction files that every supported agent reads, and green CI.

**Architecture:** `src/` layout package `super_harness` built with hatchling and managed by uv. Two repo checks live in `scripts/` (Markdown line caps, module-doc sync) and run from `make docs`, pre-commit and CI. `AGENTS.md` is the canonical agent instruction file; `CLAUDE.md` and `GEMINI.md` only import it.

**Tech Stack:** Python ≥3.12, uv, hatchling, Typer, pytest, ruff, mypy (strict), pre-commit, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-10-22-super-harness-design.md` §12 (Foundation), plus §3.1, §4.5 and §8.3 for doc content.

## Global Constraints

- Python `>=3.12`; local dev on 3.14; CI matrix 3.12 and 3.14 on ubuntu-latest and macos-latest.
- Distribution `super-harness`, import package `super_harness`, console scripts `harness` and `hrn` (alias), both pointing at `super_harness.cli:app`.
- `harness --version` prints exactly `super-harness <version>`; the version lives only in `src/super_harness/__init__.py`.
- AGENTS.md ≤ 100 lines; every `docs/**/*.md` ≤ 150 lines; `docs/superpowers/**` exempt.
- Module docs: `docs/modules/<module>/README.md` with sections Purpose · Interface · Invariants · Changes (newest first, ≤ 20 lines); updated in the same commit as the module.
- Checks print nothing on success and one line per problem on failure.
- License MIT, copyright holder `normatov13`.
- All work on branch `feat/foundation`; never commit implementation directly to `main`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## File Structure

| Path | Responsibility | Task |
|---|---|---|
| `pyproject.toml` | package metadata, dependencies, tool config | 1 |
| `uv.lock` | locked dev environment (generated) | 1 |
| `.gitignore` | ignore Python, uv and tool caches | 1 |
| `LICENSE`, `README.md` | MIT text; human overview | 1 |
| `src/super_harness/__init__.py` | `__version__` (single source) | 1 |
| `src/super_harness/cli.py` | Typer app: `--version`, `--help` | 1 |
| `tests/test_cli.py` | CLI and console-script tests | 1 |
| `docs/modules/cli/README.md` | cli module doc | 1 |
| `scripts/__init__.py` | makes checks importable by tests | 2 |
| `scripts/check_md_caps.py` | Markdown line caps | 2 |
| `tests/test_check_md_caps.py` | caps tests | 2 |
| `scripts/check_docs_sync.py` | module ↔ doc sync | 3 |
| `tests/test_check_docs_sync.py` | sync tests incl. real git repos | 3 |
| `Makefile` | setup · fmt · lint · type · test · docs · check | 4 |
| `.pre-commit-config.yaml` | local hooks via `uv run` | 4 |
| `.github/workflows/ci.yml` | `make check` matrix | 4 |
| `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` | agent instructions and pointers | 5 |
| `docs/README.md`, `docs/architecture.md`, `docs/conventions/*.md` | doc index, system map, conventions | 5 |

---

### Task 1: Package skeleton and `harness --version`

**Files:**
- Create: `pyproject.toml`, `LICENSE`, `README.md`, `src/super_harness/__init__.py`, `src/super_harness/cli.py`, `tests/test_cli.py`, `docs/modules/cli/README.md`
- Modify: `.gitignore`
- Generated: `uv.lock`

**Interfaces:**
- Produces: `super_harness.__version__: str`; `super_harness.cli.app: typer.Typer`; executables `harness`, `hrn`.

- [ ] **Step 1: Create the branch**

Run: `git switch -c feat/foundation` (skip if the worktree step already created it).

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "super-harness"
dynamic = ["version"]
description = "Run many projects at once with subscription coding-agent CLIs (Claude Code, Codex, Antigravity)."
readme = "README.md"
license = "MIT"
license-files = ["LICENSE"]
requires-python = ">=3.12"
authors = [{ name = "normatov13" }]
dependencies = ["typer>=0.12"]

[project.scripts]
harness = "super_harness.cli:app"
hrn = "super_harness.cli:app"

[dependency-groups]
dev = ["mypy>=1.13", "pre-commit>=4", "pytest>=8", "ruff>=0.8"]

[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[tool.hatch.version]
path = "src/super_harness/__init__.py"

[tool.hatch.build.targets.wheel]
packages = ["src/super_harness"]

[tool.ruff]
line-length = 100
target-version = "py312"
src = ["src", "."]

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B", "SIM", "RUF"]

[tool.mypy]
strict = true
python_version = "3.12"
files = ["src", "scripts", "tests"]

[tool.pytest.ini_options]
addopts = "-q"
testpaths = ["tests"]
pythonpath = ["."]
```

- [ ] **Step 3: Write `LICENSE`** — the standard MIT License text, first lines `MIT License`, blank line, `Copyright (c) 2026 normatov13`.

- [ ] **Step 4: Write `README.md`**

```markdown
# super-harness

Run many projects at once with the coding-agent subscriptions you already pay for (Claude Code, Codex, Antigravity), through their official CLIs, never API keys.

> Status: early development, sub-project 1 of 5. The `harness` CLI only prints its version so far.

## How it will work

1. `/to-plan-with-grill` or `/to-plan`: your agent turns a prompt into a reviewed plan.
2. `/to-ticket`: the plan becomes small tickets with importance, dependencies and touched paths.
3. `/to-loop`: tickets run through importance-based agent loops (plan, review, implement, review, security) in parallel across projects, each in its own git worktree, with loop caps you approve.
4. `/open-ui`: a local board shows every ticket, step, model, token count and code change.

## Develop

Requires [uv](https://docs.astral.sh/uv/) and GNU make.

    make setup   # environment and git hooks
    make check   # format, lint, types, tests, docs checks

Design: `docs/superpowers/specs/2026-10-22-super-harness-design.md`. Agent instructions: `AGENTS.md`.

## License

MIT
```

- [ ] **Step 5: Extend `.gitignore`** to exactly:

```gitignore
# local Claude Code settings
.claude/settings.local.json

# Python and tooling
__pycache__/
*.py[cod]
.venv/
.mypy_cache/
.pytest_cache/
.ruff_cache/
build/
dist/
*.egg-info/
```

- [ ] **Step 6: Write `src/super_harness/__init__.py`** (needed before `uv sync` can build the package)

```python
"""super-harness: run many projects at once with subscription coding-agent CLIs."""

__version__ = "0.1.0"
```

- [ ] **Step 7: Write the failing test `tests/test_cli.py`**

```python
import shutil
import subprocess

import pytest
from typer.testing import CliRunner

from super_harness import __version__
from super_harness.cli import app

runner = CliRunner()


def test_version_names_the_package() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"super-harness {__version__}"


def test_help_lists_the_version_option() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--version" in result.output


@pytest.mark.parametrize("command", ["harness", "hrn"])
def test_console_scripts_print_version(command: str) -> None:
    executable = shutil.which(command)
    assert executable, f"{command} is not on PATH; run `make setup`"
    output = subprocess.run(
        [executable, "--version"], check=True, capture_output=True, text=True
    ).stdout
    assert output.strip() == f"super-harness {__version__}"
```

- [ ] **Step 8: Install and watch it fail**

Run: `uv sync && uv run pytest tests/test_cli.py`
Expected: collection error `ModuleNotFoundError: No module named 'super_harness.cli'`.

- [ ] **Step 9: Write `src/super_harness/cli.py`**

```python
"""Command-line entry point for `harness` (alias `hrn`)."""

from typing import Annotated

import typer

from super_harness import __version__

app = typer.Typer(
    name="harness",
    help="Run many projects at once with subscription coding-agent CLIs.",
    no_args_is_help=True,
    add_completion=False,
)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"super-harness {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_print_version,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Run many projects at once with subscription coding-agent CLIs."""
```

- [ ] **Step 10: Run the tests**

Run: `uv run pytest tests/test_cli.py`
Expected: `4 passed`.

- [ ] **Step 11: Write `docs/modules/cli/README.md`**

```markdown
# cli

## Purpose

Typer command surface for `harness` (alias `hrn`): parses arguments and formats output. From sub-project 2 on, every action is delegated to `ops`.

## Interface

- `harness --version` prints `super-harness <version>` and exits 0. Skills use this line to confirm the right binary is on PATH.
- `harness --help` lists commands and options.

## Invariants

- Status and action commands print at most 5 lines by default; `--json` gives full output (spec §6).
- Exit codes: 0 ok · 1 error · 2 usage · 3 wait timeout · 4 setup needed · 5 user decision needed.
- `cli` imports only `ops` and `model` (spec §3.1).

## Changes

- 2026-10-22: skeleton with `--version` and `--help`; console scripts `harness` and `hrn`.
```

- [ ] **Step 12: Commit** (lint first: `uv run ruff format . && uv run ruff check . && uv run mypy src tests`; `scripts/` does not exist yet, so name the paths)

```bash
git add .gitignore LICENSE README.md pyproject.toml uv.lock src tests docs/modules
git commit -m "feat(cli): package skeleton with harness --version" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Markdown caps check

**Files:**
- Create: `scripts/__init__.py`, `scripts/check_md_caps.py`, `tests/test_check_md_caps.py`

**Interfaces:**
- Produces: `scripts.check_md_caps.violations(root: Path) -> list[str]` (lines `"<posix path>: <n> lines > cap <cap>"`); `scripts.check_md_caps.main(argv: list[str] | None = None) -> int` (argv[0] = root, default cwd; returns 1 when any violation, else 0, printing nothing).

- [ ] **Step 1: Write `scripts/__init__.py`**

```python
"""Repository checks run by `make docs`, pre-commit and CI."""
```

- [ ] **Step 2: Write the failing test `tests/test_check_md_caps.py`**

```python
from pathlib import Path

import pytest

from scripts.check_md_caps import main, violations


def write_lines(path: Path, count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("line\n" * count, encoding="utf-8")


def test_files_within_caps_pass_silently(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_lines(tmp_path / "AGENTS.md", 100)
    write_lines(tmp_path / "docs" / "topic.md", 150)
    assert main([str(tmp_path)]) == 0
    assert capsys.readouterr().out == ""


def test_oversized_agents_md_is_reported(tmp_path: Path) -> None:
    write_lines(tmp_path / "AGENTS.md", 101)
    assert violations(tmp_path) == ["AGENTS.md: 101 lines > cap 100"]


def test_oversized_nested_doc_is_reported(tmp_path: Path) -> None:
    write_lines(tmp_path / "docs" / "modules" / "cli" / "README.md", 151)
    assert violations(tmp_path) == ["docs/modules/cli/README.md: 151 lines > cap 150"]


def test_specs_and_plans_are_exempt(tmp_path: Path) -> None:
    write_lines(tmp_path / "docs" / "superpowers" / "specs" / "design.md", 900)
    assert violations(tmp_path) == []


def test_main_prints_each_violation_and_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_lines(tmp_path / "AGENTS.md", 120)
    assert main([str(tmp_path)]) == 1
    assert capsys.readouterr().out == "AGENTS.md: 120 lines > cap 100\n"
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run pytest tests/test_check_md_caps.py`
Expected: collection error `ModuleNotFoundError: No module named 'scripts.check_md_caps'`.

- [ ] **Step 4: Write `scripts/check_md_caps.py`**

```python
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
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_check_md_caps.py`
Expected: `5 passed`.

- [ ] **Step 6: Commit** (lint first: `uv run ruff format . && uv run ruff check . && uv run mypy`)

```bash
git add scripts tests/test_check_md_caps.py
git commit -m "feat(scripts): enforce Markdown line caps on instruction files" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Module-doc sync check

**Files:**
- Create: `scripts/check_docs_sync.py`, `tests/test_check_docs_sync.py`

**Interfaces:**
- Produces: `module_of(path: str) -> str | None`; `problems(changed: list[str]) -> list[str]` (lines `"<module>: changed without docs/modules/<module>/README.md"`); `changed_files(base: str | None, staged: bool) -> list[str]` (raises `SystemExit` whose message contains `pass a valid --base` when git fails); `main(argv: list[str] | None = None) -> int` with exactly one of `--base REF` or `--staged`.

- [ ] **Step 1: Write the failing test `tests/test_check_docs_sync.py`**

```python
import subprocess
from pathlib import Path

import pytest

from scripts.check_docs_sync import main, module_of, problems


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_module_of_maps_package_paths() -> None:
    assert module_of("src/super_harness/cli.py") == "cli"
    assert module_of("src/super_harness/store/paths.py") == "store"
    assert module_of("src/super_harness/__init__.py") is None
    assert module_of("src/super_harness/py.typed") is None
    assert module_of("tests/test_cli.py") is None


def test_module_change_without_doc_is_reported() -> None:
    assert problems(["src/super_harness/cli.py"]) == [
        "cli: changed without docs/modules/cli/README.md"
    ]


def test_module_change_with_doc_passes() -> None:
    assert problems(["src/super_harness/cli.py", "docs/modules/cli/README.md"]) == []


def test_each_module_is_reported_once() -> None:
    changed = ["src/super_harness/store/a.py", "src/super_harness/store/b.py"]
    assert problems(changed) == ["store: changed without docs/modules/store/README.md"]


def test_base_mode_fails_until_the_doc_lands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    git(tmp_path, "init", "-b", "main")
    write(tmp_path / "README.md", "base\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "base")
    git(tmp_path, "switch", "-c", "feature")
    write(tmp_path / "src" / "super_harness" / "widget.py", "X = 1\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "add widget")
    monkeypatch.chdir(tmp_path)

    assert main(["--base", "main"]) == 1
    assert capsys.readouterr().out == "widget: changed without docs/modules/widget/README.md\n"

    write(tmp_path / "docs" / "modules" / "widget" / "README.md", "# widget\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "document widget")
    assert main(["--base", "main"]) == 0


def test_staged_mode_checks_the_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    git(tmp_path, "init", "-b", "main")
    write(tmp_path / "src" / "super_harness" / "widget.py", "X = 1\n")
    git(tmp_path, "add", ".")
    monkeypatch.chdir(tmp_path)
    assert main(["--staged"]) == 1


def test_unknown_base_is_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    git(tmp_path, "init", "-b", "main")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit, match="pass a valid --base"):
        main(["--base", "nope"])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_check_docs_sync.py`
Expected: collection error `ModuleNotFoundError: No module named 'scripts.check_docs_sync'`.

- [ ] **Step 3: Write `scripts/check_docs_sync.py`**

```python
"""Fail when a package module changes without its docs/modules/<module>/README.md.

A module is a top-level package or .py file under src/super_harness/; package dunder
files and non-Python files at the top level are not modules. Prints nothing when in sync.
"""

import argparse
import subprocess
import sys

PACKAGE = "src/super_harness/"


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
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_check_docs_sync.py`
Expected: `7 passed`.

- [ ] **Step 5: Commit** (lint first: `uv run ruff format . && uv run ruff check . && uv run mypy`)

```bash
git add scripts/check_docs_sync.py tests/test_check_docs_sync.py
git commit -m "feat(scripts): require module docs to change with their modules" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Make targets, pre-commit hooks, CI

**Files:**
- Create: `Makefile`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `scripts/check_md_caps.py` (no args = cwd), `scripts/check_docs_sync.py --base REF | --staged`.
- Produces: `make setup|fmt|lint|type|test|docs|check`; variable `DOCS_BASE` (default `main`).

- [ ] **Step 1: Write `Makefile`** (recipe lines start with a TAB)

```make
DOCS_BASE ?= main

.PHONY: setup fmt lint type test docs check

setup:
	uv sync
	uv run pre-commit install

fmt:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff format --check --quiet .
	uv run ruff check --quiet .

type:
	uv run mypy --no-error-summary

test:
	uv run pytest

docs:
	uv run python scripts/check_md_caps.py
	uv run python scripts/check_docs_sync.py --base $(DOCS_BASE)

check: lint type test docs
```

- [ ] **Step 2: Run the full check and fix what it reports**

Run: `make check`
Expected: exit 0; output only pytest's `.` progress line and `16 passed`. If ruff reports formatting, run `make fmt`, re-run `make check`.

- [ ] **Step 3: Write `.pre-commit-config.yaml`** (local hooks only: they run the locked tools from `uv.lock` and fetch nothing)

```yaml
repos:
  - repo: local
    hooks:
      - id: ruff-format
        name: ruff format
        entry: uv run ruff format
        language: system
        types: [python]
      - id: ruff-check
        name: ruff check
        entry: uv run ruff check --fix
        language: system
        types: [python]
      - id: md-caps
        name: markdown caps
        entry: uv run python scripts/check_md_caps.py
        language: system
        pass_filenames: false
        files: \.md$
      - id: docs-sync
        name: module docs change with modules
        entry: uv run python scripts/check_docs_sync.py --staged
        language: system
        pass_filenames: false
        always_run: true
```

- [ ] **Step 4: Install hooks and run them on every file**

Run: `make setup && uv run pre-commit run --all-files`
Expected: every hook `Passed` (docs-sync and md-caps may show `Passed` or `(no files to check)Skipped`).

- [ ] **Step 5: Write `.github/workflows/ci.yml`** (event values reach the shell only through `env`, never inline `${{ }}`, to block script injection from branch names)

```yaml
name: ci

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  check:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest]
        python: ["3.12", "3.14"]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: astral-sh/setup-uv@v6
        with:
          python-version: ${{ matrix.python }}
      - run: uv sync
      - name: make check
        shell: bash
        env:
          EVENT: ${{ github.event_name }}
          BASE_REF: ${{ github.base_ref }}
          BEFORE: ${{ github.event.before }}
        run: |
          if [ "$EVENT" = "pull_request" ]; then
            base="origin/$BASE_REF"
          elif [ -n "$BEFORE" ] && [ "$BEFORE" != "0000000000000000000000000000000000000000" ]; then
            base="$BEFORE"
          else
            base="$(git rev-list --max-parents=0 HEAD | tail -n 1)"
          fi
          make check DOCS_BASE="$base"
```

- [ ] **Step 6: Validate the workflow parses**

Run: `uv run python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('ok')"`
Expected: `ok` (PyYAML ships with pre-commit).

- [ ] **Step 7: Commit**

```bash
git add Makefile .pre-commit-config.yaml .github/workflows/ci.yml
git commit -m "ci: make targets, pre-commit hooks and CI matrix" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Agent instruction files and docs

**Files:**
- Create: `AGENTS.md`, `GEMINI.md`, `docs/README.md`, `docs/architecture.md`, `docs/conventions/instruction-files.md`, `docs/conventions/skills.md`, `docs/conventions/memory-files.md`
- Modify: `CLAUDE.md` (content moves to `AGENTS.md`; keeps only the prefix and the import)

**Interfaces:**
- Consumes: `make docs` (Task 4) to verify caps.

- [ ] **Step 1: Find which context file `agy` reads.** Search the Antigravity CLI docs (antigravity.google/docs/cli) for its context/rules file names. Record the answer for Step 6 and Step 7. If agy does not read `AGENTS.md`, plan to add the smallest pointer it does read (e.g. its rules file containing `@AGENTS.md` or a one-line "Read AGENTS.md first").

- [ ] **Step 2: Write `AGENTS.md`**

```markdown
# AGENTS.md

super-harness lets one developer run many projects at once with the coding-agent subscriptions they already have (Claude Code, Codex, Antigravity `agy`; Gemini CLI optional), driven through the official CLIs, never API keys. Skills installed into the user's agent conduct the work, the deterministic `harness` CLI does every mechanical step, and a local UI monitors it all.

Status: sub-project 1 of 5 (Foundation). Only the CLI skeleton (`harness --version`) exists; `docs/architecture.md` tracks what is built.

## Commands

- `make setup`: install the uv environment and git hooks
- `make check`: everything CI runs (format, lint, types, tests, docs checks)
- `make fmt`: format and auto-fix
- One test: `uv run pytest tests/test_cli.py::test_version_names_the_package`
- `make docs DOCS_BASE=origin/main`: docs checks against another base

## Hard rules

1. The spec `docs/superpowers/specs/2026-10-22-super-harness-design.md` is the contract. Where it differs from `full prompt of app.md` (the original request), the spec wins. Change the spec before changing a contract.
2. A change to `src/super_harness/<module>` updates `docs/modules/<module>/README.md` in the same commit; `make docs` and the pre-commit hook enforce it.
3. Each project links to the store through one directory symlink. Never use hard links: they cannot link directories and break on status-folder moves and atomic saves.
4. Only `harness` writes store files; agents never hand-edit plan or ticket state.
5. Tickets reference their plan by id; never copy the full prompt into tickets.
6. Providers run only through their official binaries under the user's login: never read or reuse OAuth tokens, never use `claude --bare` (it skips subscription login), and strip provider API-key variables from worker environments.
7. No always-on daemon: workers are short-lived detached processes, one per job.
8. Instruction files stay within caps: this file ≤ 100 lines, files under `docs/` ≤ 150 lines (specs and plans exempt).

## Read when

- `docs/architecture.md`: adding or moving a module, or changing module dependencies
- `docs/conventions/instruction-files.md`: writing AGENTS.md, CLAUDE.md, GEMINI.md or any doc
- `docs/conventions/skills.md`: writing a skill or role skill
- `docs/conventions/memory-files.md`: touching MEMORY.md, DECISIONS.md, PROCESS.md, SETTINGS.md, plan or ticket formats
- `docs/modules/<module>/README.md`: changing that module
- `docs/superpowers/plans/`: implementing a sub-project step by step

## UI design source

The UI implements the Claude Design canvas https://claude.ai/artifact/JiMGMkbaw8qhafeaNbqU7d. In Claude Code, read it with the Artifact tool (`list_files`, then `read_file` on `project/canvas.json` and `project/*.dc.html`), not WebFetch.
```

- [ ] **Step 3: Replace `CLAUDE.md`** with exactly:

```markdown
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md
```

- [ ] **Step 4: Write `GEMINI.md`** with exactly one line: `@AGENTS.md`

- [ ] **Step 5: Write `docs/README.md`**

```markdown
# Docs index

One line per doc: what it holds and when to read it.

| Doc | Read when |
|---|---|
| `architecture.md` | adding or moving a module, or changing module dependencies |
| `conventions/instruction-files.md` | writing AGENTS.md, CLAUDE.md, GEMINI.md or anything under `docs/` |
| `conventions/skills.md` | writing a skill or role skill |
| `conventions/memory-files.md` | touching MEMORY.md, DECISIONS.md, PROCESS.md, SETTINGS.md, plan or ticket formats |
| `modules/<module>/README.md` | changing that module (one per module under `src/super_harness/`) |
| `superpowers/specs/` | the design contract of each sub-project |
| `superpowers/plans/` | step-by-step implementation plans |
```

- [ ] **Step 6: Write `docs/architecture.md`** (≤ 150 lines) with these sections and facts:
  - Intro: the contract is the spec; this page records what exists now; update the Status columns whenever a module or sub-project lands.
  - `## Flow`: the spec §3 diagram (conductor → `harness` CLI → detached workers → `claude -p` / `codex exec` / `agy -p`; store `~/.harness` as Markdown + JSONL in git; UI as FastAPI + SSE on 127.0.0.1 over the same `ops` layer).
  - `## Modules`: table Module · Responsibility · May import · Status for all 14 units of spec §3.1. Status: `cli` = skeleton (`--version`); `model`, `store`, `settings`, `memory`, `journal`, `ops` = planned SP2; `scheduler`, `workflow`, `adapters`, `gitops`, `worker` = planned SP3; `roles` = planned SP4; `ui` = planned SP5. One line: import direction is enforced by import-linter once SP2 adds the modules.
  - `## Store`: the spec §4.1 tree, marked planned (SP2), with one line on the per-project `.harness` directory symlink.
  - `## Repository layout`: `src/super_harness/` package · `scripts/` repo checks · `tests/` · `docs/` (index `docs/README.md`) · `skills/` and `.claude-plugin/` arrive in SP4.
  - `## Sub-projects`: table # · Sub-project · Status — 1 Foundation in progress (this plan); 2 Store + harness CLI, 3 Engine, 4 Skills, 5 Web UI planned.
  - `## Agent context files`: Codex reads `AGENTS.md` natively (Codex CLI is not installed on the dev machine, so this rests on its documentation); Claude Code via `CLAUDE.md` → `@AGENTS.md`; Gemini CLI via `GEMINI.md` → `@AGENTS.md`; agy: the Step 1 result.

- [ ] **Step 7: Write `docs/conventions/instruction-files.md`** (≤ 150 lines) with these sections and rules:
  - Purpose: how to write files agents read (AGENTS.md, CLAUDE.md, GEMINI.md, everything under `docs/`).
  - Layers: entry file `AGENTS.md` (overview, commands, ≤ 15 hard rules, "Read when" links) → topic docs (one subject each) → code layer (types, docstrings, config comments; never duplicated in docs).
  - Caps, enforced by `scripts/check_md_caps.py` via `make docs` and pre-commit: AGENTS.md ≤ 100 lines; `docs/**/*.md` ≤ 150 lines, aim for 50–150 for topic docs; `docs/superpowers/` exempt.
  - Pointer files: `CLAUDE.md` = the /init prefix + `@AGENTS.md`; `GEMINI.md` = `@AGENTS.md`; Codex reads AGENTS.md natively; agy per Step 1. Pointer files never hold content.
  - Writing rules (numbered): every link states what it holds and when to read it, trigger word first; every non-obvious rule says why and when it applies, and is deleted when the why expires; phrase instructions positively; give output shapes as templates, keep "never" for discipline rules and state the reason; put the most important rules at the top or bottom; one source of truth (link, never copy; never restate code or config); referenced commands are quiet on success and loud on failure; prune stale or no-op lines on every edit.
  - Module docs: `docs/modules/<module>/README.md` with Purpose · Interface · Invariants · Changes (newest first, ≤ 20 lines; older history lives in git); updated in the same commit as the module; `scripts/check_docs_sync.py` enforces it.
  - Responsibility table: File · Read by · Written by — AGENTS.md (every agent, every session · humans and agents, reviewed in PRs); `docs/modules/*` (agents changing that module · whoever changes the module); `docs/conventions/*` (anyone writing that kind of file · humans); specs and plans (anyone working on that sub-project · brainstorming and writing-plans).
  - Sources line: walkinglabs learn-harness-engineering lecture 4; HumanLayer "Skill issue"; Matt Pocock `writing-for-agents`.

- [ ] **Step 8: Write `docs/conventions/skills.md`** (≤ 150 lines) with these sections and rules:
  - Scope: installable skills `skills/<name>/SKILL.md` and role skills `src/super_harness/roles/<role>/SKILL.md` (both arrive in SP4).
  - Format: Agent Skills spec (agentskills.io) — folder name equals `name` (lowercase letters, digits, single hyphens, ≤ 64 chars); `description` ≤ 1024 chars by spec, ≤ 500 here; optional `scripts/`, `references/`, `assets/`.
  - Description: starts with "Use when", lists triggers only and never the steps (agents follow a summarised workflow and skip the body), third person.
  - Size: ≤ 80 lines and ≤ 400 words (`skill.max_lines`, `skill.max_words`); aim for ≤ 200 words.
  - Body: numbered steps; each step is a `harness …` command or one judgment, ending on a checkable condition; flags live in `harness <cmd> --help`, not in the skill; output shapes as templates.
  - Step 0 of every installed skill: `harness --version` must print `super-harness <version>`; otherwise print the install line and stop.
  - References: one level deep, named by trigger ("read `references/importance.md` when assigning importance").
  - Invocation: user commands set `disable-model-invocation: true` for Claude; model-invoked skills (e.g. `harness-memory`) need sharp triggers.
  - Test first: RED (a scenario fails without the skill) → GREEN (smallest skill that passes) → REFACTOR (close loopholes); `harness skills eval` (SP4) replays scenarios on claude, codex and agy.
  - Enforcement: `harness skills lint` (SP4) checks frontmatter, description prefix and length, caps, and that every mentioned `harness` command exists.
  - Distribution: `npx skills add <owner>/super-harness` (Claude Code → `.claude/skills/`; Codex, Antigravity, Gemini CLI, Cursor, Copilot, OpenCode → `.agents/skills/`), `harness skills install`, Claude and Codex plugin marketplaces.

- [ ] **Step 9: Write `docs/conventions/memory-files.md`** (≤ 150 lines) with these sections and rules:
  - Status line: formats are the contract for SP2, which implements them.
  - The spec §4.5 table: File · Scope · Read by · Written by · Cap for MEMORY.md (global, 200 lines), DECISIONS.md (global, `[project]` tags, 300 lines then archive), PROCESS.md (project, 100 lines), SETTINGS.md (project, schema-validated), ticket `## Handoff` (15 lines).
  - Line formats: MEMORY.md sections `## Working style` · `## Goals` · `## Preferences` · `## Turned down`; DECISIONS.md entry `- YYYY-MM-DD [project] decision. why: … rejected: …`; one fact per line, about 20 words at most.
  - Writing: only through `harness memory add` (attributed in the journal); lines marked `(pin)` survive compaction; compaction runs when a file passes its cap, uses the cheapest configured model, and is accepted only if under the cap with every pin kept; history stays in the store's git.
  - SETTINGS.md: whole file is YAML (`#` lines are comments that read as headings); copied from `~/.harness/defaults/` once and never overwritten; validated by harness, unknown keys rejected; agents never parse it and ask `harness` instead.
  - PROCESS.md: per project; how the project builds and tests plus process notes; ≤ 100 lines.
  - Plans and tickets: formats in spec §4.4; one plan file per request holds the verbatim prompt; one file per ticket, moved between `in_queue/`, `in_process/`, `done/`; agents never hand-edit frontmatter; `## Handoff` is replaced every step.

- [ ] **Step 10: Run the checks**

Run: `make check`
Expected: exit 0, no caps or sync output.

- [ ] **Step 11: Check agy actually loads the instructions** (the user's own `agy` login; one short prompt)

Run from the repo root: `agy -p "Quote hard rule 3 from this project's agent instructions, or reply NONE." --output-format json`
Expected: the `response` field quotes rule 3 ("Each project links to the store through one directory symlink…"). If stdout is empty with exit 0 (agy's reported pipe bug), re-run under a pseudo-terminal: `script -qec '<same command>' /dev/null`. If it replies NONE, add the pointer found in Step 1, re-run, and record the result in `docs/architecture.md` § Agent context files. If agy is not signed in, record "not verified: agy not signed in" there.

- [ ] **Step 12: Commit**

```bash
git add AGENTS.md CLAUDE.md GEMINI.md docs/README.md docs/architecture.md docs/conventions
git commit -m "docs: agent instruction files, conventions and architecture map" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Acceptance

**Files:** none changed unless a check fails.

- [ ] **Step 1: Fresh clone passes**

Run:
```bash
SCRATCH="$(mktemp -d)"
git clone -q -b feat/foundation /var/www/my-apps/super-harness "$SCRATCH/clone"
cd "$SCRATCH/clone" && make setup && make check DOCS_BASE=origin/main
```
Expected: exit 0. Steps 2–3 run inside `$SCRATCH/clone`.

- [ ] **Step 2: Both console scripts work**

Run: `uv run harness --version && uv run hrn --version`
Expected: `super-harness 0.1.0` twice.

- [ ] **Step 3: Deliberate violations fail, then pass** (in the clone only)

```bash
printf 'X = 1\n' > src/super_harness/widget.py && git add -A && git commit -qm wip --no-verify
make docs DOCS_BASE=origin/main          # expect: widget: changed without docs/modules/widget/README.md
mkdir -p docs/modules/widget && printf '# widget\n' > docs/modules/widget/README.md
git add -A && git commit -qm doc --no-verify
make docs DOCS_BASE=origin/main          # expect: exit 0
seq 151 > docs/too-long.md && make docs DOCS_BASE=origin/main   # expect: docs/too-long.md: 151 lines > cap 150
```

- [ ] **Step 4: Spec §12.3 checklist** — tick each item against the evidence above; CI green is confirmed after the branch is pushed (the user decides when to push).

- [ ] **Step 5: Finish the branch** with superpowers:finishing-a-development-branch.
