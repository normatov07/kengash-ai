"""Command-line entry point for `harness` (alias `hrn`)."""

import dataclasses
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

import typer

from super_harness import __version__
from super_harness.model import Folder, HarnessError, PlanMode, UserError
from super_harness.ops import plans, projects, queue, status, tickets, workspace

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
Only = Annotated[str | None, typer.Option("--project", "-p", help="Look only in this project.")]
By = Annotated[
    str, typer.Option("--by", envvar="HARNESS_AGENT", help="Who is acting, for the journal.")
]


@settings_app.command("show")
def settings_show(project: Project = None, as_json: AsJson = False) -> None:
    """Print the resolved settings as YAML."""
    with _errors():
        if as_json:
            resolved = workspace.settings_for(project, Path.cwd())
            text = json.dumps(resolved.model_dump(mode="json"), indent=2) + "\n"
        else:
            text = workspace.settings_yaml(project, Path.cwd())
    typer.echo(text, nl=False)


@settings_app.command("get")
def settings_get(
    key: Annotated[str, typer.Argument(help="Dotted key, e.g. loop_max.critical.")],
    project: Project = None,
    as_json: AsJson = False,
) -> None:
    """Print one setting; lists and mappings print as JSON."""
    with _errors():
        value = workspace.setting(key, project, Path.cwd())
    typer.echo(value if isinstance(value, str) and not as_json else json.dumps(value))


@settings_app.command("check")
def settings_check(project: Project = None, as_json: AsJson = False) -> None:
    """Validate settings; prints problems only."""
    with _errors():
        problems = workspace.settings_problems(project, Path.cwd())
    if as_json:
        typer.echo(json.dumps({"problems": problems}, indent=2))
    else:
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
    by: By = "unknown",
    project: Project = None,
    as_json: AsJson = False,
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
    if as_json:
        typer.echo(
            json.dumps({**dataclasses.asdict(result), "over_cap": result.over_cap}, indent=2)
        )
    elif not result.added:
        typer.echo(f"{result.file}: already recorded")
    else:
        typer.echo(f"{result.file} +1 line ({result.lines}/{result.cap})")
        if result.over_cap:
            typer.echo(f"warning: {result.file} is over its {result.cap}-line cap; compact it soon")


@memory_app.command("show")
def memory_show(
    decisions: Annotated[bool, typer.Option("--decisions", help="Show DECISIONS.md.")] = False,
    project: Project = None,
    as_json: AsJson = False,
) -> None:
    """Print MEMORY.md, or the decisions of one project plus the global ones."""
    with _errors():
        text = workspace.recall(decisions, project, Path.cwd())
    if as_json:
        name = "DECISIONS.md" if decisions else "MEMORY.md"
        typer.echo(json.dumps({"file": name, "text": text}, indent=2))
    else:
        typer.echo(text, nl=False)


@app.command()
def context(project: Project = None, as_json: AsJson = False) -> None:
    """Print the conductor's digest: memory, process headings, open gates."""
    with _errors():
        digest = workspace.context(project, Path.cwd())
    if as_json:
        _emit_json(digest)
        return
    parts = [digest.memory.rstrip()]
    if digest.project is not None:
        headings = "\n".join(digest.process) or "(empty)"
        parts.append(f"# PROCESS.md ({digest.project})\n{headings}")
        gates = [f"- {gate.id} {gate.sub_status}: {gate.title}" for gate in digest.gates]
        parts.append("# Open gates\n" + ("\n".join(gates) or "none"))
    typer.echo("\n\n".join(parts))


plan_app = typer.Typer(help="Plans: the user's prompt and the agreed design.", no_args_is_help=True)
app.add_typer(plan_app, name="plan")

PlanId = Annotated[str, typer.Argument(help="Plan id, 8 hex digits.")]


def _stdin(what: str) -> str:
    """Text piped on stdin; an interactive terminal is refused instead of waited on."""
    if sys.stdin.isatty():
        raise UserError(f"pipe the {what} on stdin")
    return sys.stdin.read()


def _emit(result: Any, as_json: bool, line: str) -> None:
    if as_json:
        _emit_json(result)
    else:
        typer.echo(line)


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


@plan_app.command("new")
def plan_new(
    title: Annotated[str, typer.Option("--title", help="One line naming the plan.")],
    mode: Annotated[PlanMode, typer.Option("--mode", help="grill, direct or quick.")],
    project: Project = None,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Start a plan from the user's prompt on stdin, kept verbatim."""
    with _errors():
        result = plans.new_plan(
            _stdin("prompt"), title=title, mode=mode, project=project, cwd=Path.cwd(), by=by
        )
    _emit(result, as_json, f"plan {result.id} {result.status}")


@plan_app.command("save")
def plan_save(
    plan_id: PlanId, project: Only = None, by: By = "unknown", as_json: AsJson = False
) -> None:
    """Replace plan sections with `## Section` Markdown from stdin; the plan becomes a draft."""
    with _errors():
        result = plans.save_plan(plan_id, _stdin("plan sections"), project=project, by=by)
    line = f"plan {result.id} {result.status}, {_plural(len(result.sections), 'section')}"
    _emit(result, as_json, line)


@plan_app.command("show")
def plan_show(plan_id: PlanId, project: Only = None, as_json: AsJson = False) -> None:
    """Print the plan file."""
    with _errors():
        doc = plans.show_plan(plan_id, project=project)
    if as_json:
        _emit_json(doc)
    else:
        typer.echo(doc.text, nl=False)


@plan_app.command("approve")
def plan_approve(
    plan_id: PlanId,
    skip_review: Annotated[
        bool, typer.Option("--skip-review", help="Approve without a plan review.")
    ] = False,
    project: Only = None,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Record the user's approval of a draft plan."""
    with _errors():
        result = plans.approve_plan(plan_id, skip_review=skip_review, project=project, by=by)
    _emit(result, as_json, f"plan {result.id} approved")


@plan_app.command("reject")
def plan_reject(
    plan_id: PlanId,
    why: Annotated[str, typer.Option("--why", help="One line: why the user rejects it.")],
    project: Only = None,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Record the user's rejection of a plan."""
    with _errors():
        result = plans.reject_plan(plan_id, why, project=project, by=by)
    _emit(result, as_json, f"plan {result.id} rejected")


ticket_app = typer.Typer(help="Tickets: one vertical slice of a plan each.", no_args_is_help=True)
app.add_typer(ticket_app, name="ticket")

TicketId = Annotated[str, typer.Argument(help="Ticket id, 8 hex digits.")]
Here = Annotated[
    str | None,
    typer.Option(
        "--project", "-p", help="Project slug; default: the project here, else every project."
    ),
]
MAX_LINES = 5
Every = Annotated[
    str | None,
    typer.Option("--project", "-p", help="Only this project; default: every project."),
]


def _capped(lines: list[str], command: str) -> list[str]:
    """At most MAX_LINES lines; the last one says how many more `command` shows."""
    if len(lines) <= MAX_LINES:
        return lines
    more = len(lines) - MAX_LINES + 1
    return [*lines[: MAX_LINES - 1], f"+{more} more; run: {command}"]


def _ticket_lines(lines: list[tickets.TicketLine], as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps([dataclasses.asdict(line) for line in lines], indent=2))
        return
    for line in lines:
        typer.echo(f"{line.id} {line.status} {line.importance} {line.project}: {line.title}")


@ticket_app.command("add")
def ticket_add(
    plan: Annotated[str, typer.Option("--plan", help="The plan these tickets slice.")],
    file: Annotated[
        Path | None,
        typer.Option(
            "--file", exists=True, dir_okay=False, help="YAML or JSON list; default: stdin."
        ),
    ] = None,
    project: Only = None,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Add tickets to an approved plan from a YAML or JSON list (SP2 spec §4)."""
    with _errors():
        text = file.read_text(encoding="utf-8") if file else _stdin("ticket list")
        batch = tickets.add_tickets(plan, text, project=project, by=by)
    count = len(batch.tickets)
    ready = sum(new.status == "in_queue/ready" for new in batch.tickets)
    ids = ", ".join(new.id for new in batch.tickets)
    line = f"{_plural(count, 'ticket')}: {ids} ({ready} ready, {count - ready} blocked)"
    _emit(batch, as_json, line)


@ticket_app.command("show")
def ticket_show(ticket_id: TicketId, project: Only = None, as_json: AsJson = False) -> None:
    """Print the ticket file."""
    with _errors():
        doc = tickets.show_ticket(ticket_id, project=project)
    if as_json:
        _emit_json(doc)
    else:
        typer.echo(doc.text, nl=False)


@ticket_app.command("list")
def ticket_list(
    project: Here = None,
    folder: Annotated[Folder | None, typer.Option("--folder", help="Only this folder.")] = None,
    as_json: AsJson = False,
) -> None:
    """One line per ticket: id, status, importance, project and title."""
    with _errors():
        lines = tickets.list_tickets(project=project, cwd=Path.cwd(), folder=folder)
    _ticket_lines(lines, as_json)


@ticket_app.command("find")
def ticket_find(
    text: Annotated[str, typer.Argument(help="Words to look for, in any case.")],
    project: Here = None,
    as_json: AsJson = False,
) -> None:
    """Tickets whose title, tags or text contain TEXT."""
    with _errors():
        lines = tickets.find_tickets(text, project=project, cwd=Path.cwd())
    _ticket_lines(lines, as_json)


@ticket_app.command("set")
def ticket_set(
    ticket_id: TicketId,
    pairs: Annotated[
        list[str], typer.Argument(metavar="KEY=VALUE...", help="e.g. tags=[api,auth] loop_max=8")
    ],
    project: Only = None,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Change title, importance, workflow, gate, loop_max, touches, depends_on or tags."""
    with _errors():
        result = tickets.set_fields(ticket_id, pairs, project=project, by=by)
    _emit(result, as_json, f"ticket {result.id} updated")


@ticket_app.command("move")
def ticket_move(
    ticket_id: TicketId,
    target: Annotated[
        str, typer.Argument(metavar="FOLDER[/SUB]", help="e.g. done or in_queue/parked.")
    ],
    why: Annotated[str, typer.Option("--why", help="One line: why it moves.")],
    project: Only = None,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Move a ticket; queued tickets then turn ready or blocked to match their dependencies."""
    with _errors():
        moved = tickets.move_ticket(ticket_id, target, why, project=project, by=by)
    if as_json:
        _emit_json(moved)
        return
    typer.echo(f"ticket {moved.id} → {moved.after}")
    if moved.ready:
        typer.echo(f"ready: {', '.join(moved.ready)}")
    if moved.blocked:
        typer.echo(f"blocked: {', '.join(moved.blocked)}")


@app.command("status")
def show_status(project: Every = None, as_json: AsJson = False) -> None:
    """Board summary: tickets per folder for each project, then gates waiting on the user."""
    with _errors():
        board = status.board(project)
    if as_json:
        _emit_json(board)
        return
    lines = [
        f"{item.project}: {item.folders['in_queue']} in_queue, "
        f"{item.folders['in_process']} in_process, {item.folders['done']} done"
        for item in board.projects
    ]
    lines += [
        f"- {gate.id} {gate.sub_status}: {gate.title} ({item.project})"
        for item in board.projects
        for gate in item.gates
    ]
    if not lines:
        lines = ["no projects; run: harness init"]
    for line in _capped(lines, "harness status --json"):
        typer.echo(line)


@app.command("next")
def show_next(project: Every = None, as_json: AsJson = False) -> None:
    """Tickets that can start now, in the order to start them."""
    with _errors():
        found = queue.next_tickets(project)
    if as_json:
        _emit_json(found)
        return
    lines = [
        f"{item.id} {item.project} {item.importance} {item.step}→{item.provider} {item.title}"
        for item in found.runnable
    ] or [_nothing_runnable(found)]
    for line in _capped(lines, "harness next --json"):
        typer.echo(line)


def _nothing_runnable(found: queue.Queue) -> str:
    counts = [
        f"{count} {label}"
        for count, label in (
            (len(found.held_back), "held back"),
            (found.blocked, "blocked"),
            (found.running, "running"),
            (found.gates, "at gates"),
            (found.paused, "paused"),
        )
        if count
    ]
    return f"nothing runnable: {', '.join(counts) or 'the queue is empty'}"
