"""Command-line entry point for `harness` (alias `hrn`)."""

import dataclasses
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

import typer

from super_harness import __version__
from super_harness.model import HarnessError
from super_harness.ops import projects

app = typer.Typer(
    name="harness",
    help="Run many projects at once with subscription coding-agent CLIs.",
    no_args_is_help=True,
    add_completion=False,
)

AsJson = Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")]


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


@contextmanager
def _errors() -> Iterator[None]:
    """Turn a harness error into one stderr line and the spec's exit code."""
    try:
        yield
    except HarnessError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(error.exit_code) from None


def _emit_json(result: Any) -> None:
    typer.echo(json.dumps(dataclasses.asdict(result), default=str, indent=2))


def _emit_link(verb: str, result: projects.InitResult) -> None:
    typer.echo(f"{verb} {result.slug}: {result.repo / '.harness'} -> {result.link_target}")
    for warning in result.warnings:
        typer.echo(f"warning: {warning}")


@app.command()
def init(
    path: Annotated[
        Path | None, typer.Argument(help="A folder inside the project; default: current folder.")
    ] = None,
    as_json: AsJson = False,
) -> None:
    """Register a project and link its .harness folder to the store."""
    with _errors():
        result = projects.init_project(path or Path.cwd())
    if as_json:
        _emit_json(result)
    elif result.created:
        _emit_link("initialized", result)
    else:
        typer.echo(f"ok {result.slug}: already initialized")
        for warning in result.warnings:
            typer.echo(f"warning: {warning}")


@app.command()
def doctor(
    fix: Annotated[bool, typer.Option("--fix", help="Repair links and exclude entries.")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", help="Print problems only.")] = False,
    scan: Annotated[
        Path | None,
        typer.Option(metavar="DIR", help="Also find unmanaged .harness folders under DIR."),
    ] = None,
    as_json: AsJson = False,
) -> None:
    """Check projects, links and documents; --fix repairs links."""
    with _errors():
        report = projects.doctor(fix=fix, scan=scan)
    if as_json:
        _emit_json(report)
    else:
        for problem in report.problems:
            prefix = f"{problem.slug}: " if problem.slug else ""
            typer.echo(prefix + problem.message)
        if not report.problems and not quiet:
            plural = "" if report.projects == 1 else "s"
            typer.echo(f"ok: {report.projects} project{plural}")
    if any(not problem.fixed for problem in report.problems):
        raise typer.Exit(1)


@app.command()
def link(
    slug: Annotated[str, typer.Argument(help="Project slug from the registry.")],
    new_path: Annotated[Path, typer.Argument(help="Where the project lives now.")],
    as_json: AsJson = False,
) -> None:
    """Point a moved project at the store again."""
    with _errors():
        result = projects.relink(slug, new_path)
    if as_json:
        _emit_json(result)
    else:
        _emit_link("linked", result)


@app.command()
def adopt(
    path: Annotated[Path, typer.Argument(help="Project folder that holds a real .harness/.")],
    as_json: AsJson = False,
) -> None:
    """Move a project's real .harness/ folder into the store and link it."""
    with _errors():
        result = projects.adopt(path)
    if as_json:
        _emit_json(result)
    else:
        typer.echo(
            f"adopted {result.slug}: {result.added} new, {result.conflicts} conflicts; "
            f"original kept in {result.archive}"
        )
