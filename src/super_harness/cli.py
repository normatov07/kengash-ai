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
from super_harness.ops import projects, workspace

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


settings_app = typer.Typer(
    help="Read resolved settings; agents never parse SETTINGS.md.", no_args_is_help=True
)
memory_app = typer.Typer(help="Global memory and decisions.", no_args_is_help=True)
app.add_typer(settings_app, name="settings")
app.add_typer(memory_app, name="memory")

Project = Annotated[
    str | None,
    typer.Option(
        "--project", "-p", help="Project slug; default: the project containing this folder."
    ),
]


@settings_app.command("show")
def settings_show(project: Project = None) -> None:
    """Print the resolved settings as YAML."""
    with _errors():
        text = workspace.settings_yaml(project, Path.cwd())
    typer.echo(text, nl=False)


@settings_app.command("get")
def settings_get(
    key: Annotated[str, typer.Argument(help="Dotted key, e.g. loop_max.critical.")],
    project: Project = None,
) -> None:
    """Print one setting; lists and mappings print as JSON."""
    with _errors():
        value = workspace.setting(key, project, Path.cwd())
    typer.echo(value if isinstance(value, str) else json.dumps(value))


@settings_app.command("check")
def settings_check(project: Project = None) -> None:
    """Validate settings; prints problems only."""
    with _errors():
        problems = workspace.settings_problems(project, Path.cwd())
    for problem in problems:
        typer.echo(problem)
    if problems:
        raise typer.Exit(1)


@memory_app.command("add")
def memory_add(
    text: Annotated[str, typer.Argument(help="One fact, one line, about 20 words.")],
    why: Annotated[str, typer.Option("--why", help="Why this is worth remembering.")],
    section: Annotated[
        str, typer.Option(help="Working style, Goals, Preferences or Turned down.")
    ] = "Preferences",
    decision: Annotated[bool, typer.Option("--decision", help="Write to DECISIONS.md.")] = False,
    rejected: Annotated[
        str | None, typer.Option(help="With --decision: the alternative turned down.")
    ] = None,
    by: Annotated[str, typer.Option(envvar="HARNESS_AGENT", help="Who is writing.")] = "unknown",
    project: Project = None,
) -> None:
    """Remember one fact or one decision."""
    with _errors():
        result = workspace.remember(
            text,
            why,
            section=section,
            decision=decision,
            rejected=rejected,
            project=project,
            cwd=Path.cwd(),
            by=by,
        )
    if not result.added:
        typer.echo(f"{result.file}: already recorded")
        return
    typer.echo(f"{result.file} +1 line ({result.lines}/{result.cap})")
    if result.over_cap:
        typer.echo(f"warning: {result.file} is over its {result.cap}-line cap; compact it soon")


@memory_app.command("show")
def memory_show(
    decisions: Annotated[bool, typer.Option("--decisions", help="Show DECISIONS.md.")] = False,
    project: Project = None,
) -> None:
    """Print MEMORY.md, or the decisions of one project plus the global ones."""
    with _errors():
        text = workspace.recall(decisions, project, Path.cwd())
    typer.echo(text, nl=False)


@app.command()
def context(project: Project = None) -> None:
    """Print the conductor's digest: memory, process headings, open gates."""
    with _errors():
        text = workspace.context(project, Path.cwd())
    typer.echo(text, nl=False)
