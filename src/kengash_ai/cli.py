"""Command-line entry point for `kengash` (0.1.0's `harness` and `hrn` until 0.3.0)."""

import contextlib
import dataclasses
import json
import signal
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer

from kengash_ai import __version__, scheduler
from kengash_ai.model import Folder, KengashError, NeedsUser, PlanMode, UserError
from kengash_ai.ops import (
    activity,
    agent_config,
    changes,
    compaction,
    conductors,
    controls,
    evals,
    harvest,
    loops,
    merging,
    plans,
    progress,
    projects,
    queue,
    relay,
    reviews,
    skills,
    stats,
    status,
    tickets,
    ui_server,
    waiting,
    workflows,
    workspace,
)
from kengash_ai.ops import watch as watching

REFRESH_S = 2.0  # how often `kengash watch` redraws (SP13)

app = typer.Typer(
    name="kengash",
    help="Run many projects at once with subscription coding-agent CLIs.",
    no_args_is_help=True,
    add_completion=False,
)

AsJson = Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")]


def _require_posix() -> None:
    """kengash drives process groups and folder links: Linux and macOS (system spec §1)."""
    if sys.platform == "win32":
        typer.echo("kengash runs on Linux and macOS; on Windows use WSL", err=True)
        raise typer.Exit(4)


def _prepare() -> None:
    """Every run starts here: a supported platform, then a 0.1.0 store moved once."""
    _require_posix()
    note = projects.migrate_home()
    if note is not None:
        typer.echo(note, err=True)


def _print_version(value: bool) -> None:
    _prepare()
    if value:
        typer.echo(f"kengash-ai {__version__}")
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
    _prepare()


@contextmanager
def _errors() -> Iterator[None]:
    """Turn a kengash error into one stderr line and the spec's exit code."""
    try:
        yield
    except KengashError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(error.exit_code) from None


def _project(value: str | None) -> str | None:
    """`--project` takes a project name or a folder; commands only ever see the slug."""
    if value is None:
        return None
    with _errors():
        return workspace.project_slug(value, Path.cwd())


def _emit_json(result: Any) -> None:
    typer.echo(json.dumps(dataclasses.asdict(result), default=str, indent=2))


def _emit_link(verb: str, result: projects.InitResult) -> None:
    typer.echo(f"{verb} {result.slug}: {result.link} -> {result.link_target}")
    for warning in result.warnings:
        typer.echo(f"warning: {warning}")


@app.command()
def init(
    path: Annotated[
        Path | None, typer.Argument(help="A folder inside the project; default: current folder.")
    ] = None,
    as_json: AsJson = False,
) -> None:
    """Register a project and link its .kengash folder to the store."""
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
        typer.Option(metavar="DIR", help="Also find unmanaged .kengash folders under DIR."),
    ] = None,
    as_json: AsJson = False,
) -> None:
    """Check projects, links, documents, providers and repo trust; --fix repairs links."""
    with _errors():
        report = projects.doctor(fix=fix, scan=scan)
    if as_json:
        _emit_json(report)
    else:
        for problem in report.problems:
            prefix = f"{problem.slug}: " if problem.slug else ""
            typer.echo(
                prefix
                + ("warning: " if problem.warning and not problem.fixed else "")
                + problem.message
            )
        for note in [] if quiet else report.notes:
            typer.echo(f"note: {note.message}")
        if not report.problems and not quiet:
            plural = "" if report.projects == 1 else "s"
            typer.echo(f"ok: {report.projects} project{plural}")
    if any(not problem.fixed and not problem.warning for problem in report.problems):
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
    path: Annotated[Path, typer.Argument(help="Project folder that holds a real .kengash/.")],
    as_json: AsJson = False,
) -> None:
    """Move a project's real .kengash/ folder into the store and link it."""
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
        "--project",
        "-p",
        callback=_project,
        help="Project name or folder; default: the project containing this folder.",
    ),
]
Only = Annotated[
    str | None,
    typer.Option(
        "--project", "-p", callback=_project, help="Look only in this project (name or folder)."
    ),
]
By = Annotated[
    str,
    typer.Option(
        "--by", envvar=["KENGASH_AGENT", "HARNESS_AGENT"], help="Who is acting, for the journal."
    ),
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
        str | None,
        typer.Option(help="Working style, Goals, Preferences (the default) or Turned down."),
    ] = None,
    decision: Annotated[bool, typer.Option("--decision", help="Write to DECISIONS.md.")] = False,
    process: Annotated[
        bool, typer.Option("--process", help="Append to the project's PROCESS.md notes.")
    ] = False,
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
            process=process,
        )
    if as_json:
        typer.echo(
            json.dumps({**dataclasses.asdict(result), "over_cap": result.over_cap}, indent=2)
        )
    elif not result.added:
        typer.echo(f"{result.file}: already recorded")
    else:
        typer.echo(f"{result.file} +1 line ({result.lines}/{result.cap})")
        if result.compacting:
            typer.echo(
                f"{result.file} is over its {result.cap}-line cap; compacting it in the background"
            )
        elif result.over_cap:
            typer.echo(f"warning: {result.file} is over its {result.cap}-line cap; compact it soon")


@memory_app.command("compact")
def memory_compact(
    timeout: Annotated[
        float, typer.Option("--timeout", min=0, help="Seconds to wait for the result (exit 3).")
    ] = 540,
    as_json: AsJson = False,
) -> None:
    """Compact MEMORY.md on `memory.compactor` and wait; pinned lines always survive."""
    with _errors():
        outcome = compaction.compact_memory(timeout=timeout)
    if as_json:
        _emit_json(outcome)
    elif outcome.accepted:
        typer.echo(f"MEMORY.md {outcome.before} → {outcome.after} lines")
    else:
        typer.echo(f"MEMORY.md kept ({outcome.before} lines): {outcome.reason}", err=True)
    if not outcome.accepted:
        raise typer.Exit(1)


@memory_app.command("harvest")
def memory_harvest(
    hook: Annotated[
        bool, typer.Option("--hook", help="Read a Claude Code hook's JSON on stdin.")
    ] = False,
    plan: Annotated[str | None, typer.Option("--plan", help="Harvest a plan by id.")] = None,
    project: Only = None,
) -> None:
    """Record what the user settled, from a plan or a Claude Code session."""
    if hook:
        harvest.from_hook(sys.stdin.read())  # silent and always exit 0: it runs as a hook
        return
    with _errors():
        if plan is None:
            raise UserError("say what to harvest: --plan <id>")
        queued = harvest.queue_plan(plan, project)
    typer.echo("harvest queued" if queued else "nothing to harvest")


@memory_app.command("forget")
def memory_forget(
    text: Annotated[str, typer.Argument(help="Words from the one line to remove.")],
    by: By = "unknown",
    project: Project = None,
) -> None:
    """Remove one line from MEMORY.md, DECISIONS.md or the project's PROCESS.md."""
    with _errors():
        line = workspace.forget(text, project, Path.cwd(), by)
    typer.echo(f"forgot: {line}")


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
        if digest.auto:
            parts.append("# Mode\nloop_start: auto")
    parts.append(f"# Record\n{digest.record}")
    if digest.recent:
        lines = "\n".join(digest.recent)
        undo = 'Tell the user what was recorded; kengash memory forget "<words>" removes a line.'
        parts.append(f"# Recorded from what the user said\n{lines}\n{undo}")
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


@plan_app.command("review")
def plan_review(
    plan_id: PlanId,
    timeout: Annotated[
        float, typer.Option("--timeout", min=0, help="Seconds to wait for the round (exit 3).")
    ] = 540,
    project: Only = None,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Run the plan's next review round, on another provider, and wait for its verdict."""
    with _errors():
        result = reviews.review_plan(plan_id, project=project, by=by, timeout=timeout)
    if as_json:
        typer.echo(json.dumps({**dataclasses.asdict(result), "used_up": result.used_up}, indent=2))
    else:
        count = _plural(len(result.findings), "finding")
        lines = [f"plan {result.id} round {result.round}: {result.verdict}, {count}"]
        lines += [f"warning: {result.warning}"] if result.warning else []
        for line in _capped([*lines, *result.findings], f"kengash plan show {result.id}"):
            typer.echo(line)
    if result.used_up:
        typer.echo(reviews.used_up_message(result.round, result.max), err=True)
        raise typer.Exit(5)


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
    lines = [f"plan {result.id} approved"]
    if result.decisions:
        lines.append(f"DECISIONS.md +{result.decisions} line{'' if result.decisions == 1 else 's'}")
    lines += [f"warning: {warning}" for warning in result.warnings]
    _emit(result, as_json, "\n".join(lines))


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
        "--project",
        "-p",
        callback=_project,
        help="Project name or folder; default: the project here, else every project.",
    ),
]
MAX_LINES = 5
Every = Annotated[
    str | None,
    typer.Option(
        "--project",
        "-p",
        callback=_project,
        help="Only this project (name or folder); default: every project.",
    ),
]


def _capped(lines: list[str], command: str, limit: int = MAX_LINES) -> list[str]:
    """At most `limit` lines; the last one says how many more `command` shows."""
    if len(lines) <= limit:
        return lines
    more = len(lines) - limit + 1
    return [*lines[: limit - 1], f"+{more} more; run: {command}"]


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
    check: Annotated[
        bool, typer.Option("--check", help="Report the graph's shape; create nothing.")
    ] = False,
    project: Only = None,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Add tickets to an approved plan from a YAML or JSON list (SP2 spec §4)."""
    if check:
        with _errors():
            text = file.read_text(encoding="utf-8") if file else _stdin("ticket list")
            report = tickets.check_batch(plan, text, project=project)
        if as_json:
            _emit_json(report)
        else:
            typer.echo("\n".join(_batch_lines(report)))
        return
    with _errors():
        text = file.read_text(encoding="utf-8") if file else _stdin("ticket list")
        batch = tickets.add_tickets(plan, text, project=project, by=by)
    count = len(batch.tickets)
    ready = sum(new.status == "in_queue/ready" for new in batch.tickets)
    ids = ", ".join(new.id for new in batch.tickets)
    line = f"{_plural(count, 'ticket')}: {ids} ({ready} ready, {count - ready} blocked)"
    if batch.shape is not None:
        line += f"\n{_shape_line(batch.shape)}"
    _emit(batch, as_json, line)
    relay.advance_quietly()  # a loop that is on starts what was just added (SP20)


def _shape_line(shape: scheduler.Shape) -> str:
    return (
        f"graph: {_plural(shape.tickets, 'ticket')}, {_plural(shape.levels, 'level')}, "
        f"up to {shape.widest} at once"
    )


def _batch_lines(report: tickets.BatchCheck) -> list[str]:
    """`ticket add --check`, one finding per line (SP18 spec §3.6)."""
    lines = [_shape_line(report.shape)]
    lines += [
        f"chokepoint: {name} has {n} tickets behind it" for name, n in report.shape.chokepoints
    ]
    lines += [f"one at a time: {a} and {b} share {path}" for a, b, path in report.serial]
    lines += [f"too broad: {name} claims {path}" for name, path in report.broad]
    lines += [
        f"hot file: {name} changed by {n} tickets, claimed by {', '.join(who)}"
        for name, n, who in report.hot
    ]
    return lines if len(lines) > 1 else [*lines, "no problems found"]


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
    relay.advance_quietly()  # a change can free a ticket a loop is waiting for (SP20)


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
    relay.advance_quietly()  # a move can free the tickets behind it (SP20)
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
        lines = ["no projects; run: kengash init"]
    for line in _capped(lines, "kengash status --json"):
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
    lines += [_stuck_line(item) for item in found.stuck]
    for line in _capped(lines, "kengash next --json"):
        typer.echo(line)


@app.command("stats")
def show_stats(
    project: Every = None,
    days: Annotated[int, typer.Option("--days", min=1, help="How many days back.")] = 7,
    as_json: AsJson = False,
) -> None:
    """What runs cost and what they bought: parallelism, first-pass rate, tokens, gates."""
    with _errors():
        found = stats.report(project, days)
    if as_json:
        _emit_json(found)
        return
    busy = ", ".join(f"{n} workers {m} min" for n, m in found.minutes.items()) or "none"
    typer.echo(f"parallel: mean {found.mean_workers:.2f} workers when busy ({busy})")
    per = f", {found.tokens // found.merged:,} tokens per merged ticket" if found.merged else ""
    typer.echo(f"tickets: {found.merged} merged, {found.first_pass} on the first loop{per}")
    for row in found.models:
        typer.echo(
            f"implementer {row.cli}: {row.runs} runs, {row.tokens:,} tokens, "
            f"next review passed {row.passed} of {row.reviewed}"
        )
    gates = ", ".join(f"{n} {cause}" for cause, n in found.gates.items()) or "none"
    typer.echo(f"gates: {gates}")
    if found.quota_minutes:
        typer.echo(f"waited {found.quota_minutes} min for subscription limits")


def _stuck_line(item: queue.Stuck) -> str:
    return f"waiting on {item.id} ({item.status}): {item.behind} tickets behind it"


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


Ids = Annotated[list[str], typer.Argument(help="Ticket ids, 8 hex digits each.")]


@app.command("run")
def run_tickets(
    ticket_ids: Ids,
    steps: Annotated[
        int | None, typer.Option("--steps", min=1, help="Pause after this many steps.")
    ] = None,
    project: Only = None,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Claim tickets and start a detached worker for each; returns at once."""
    with _errors():
        result = controls.run_tickets(ticket_ids, steps=steps, project=project, by=by)
    if as_json:
        _emit_json(result)
    else:
        lines = [_watched(f"started {s.id} {s.step}→{s.provider}", s.watch) for s in result.started]
        lines += [f"skipped {tid}: {reason}" for tid, reason in result.skipped.items()]
        for line in _capped(lines, "kengash run --json"):
            typer.echo(line)
    if not result.started:
        raise typer.Exit(1)


@app.command("approve")
def approve_ticket(
    ticket_id: TicketId,
    loops: Annotated[int | None, typer.Option("--loops", min=1, help="Loops to add.")] = None,
    tokens: Annotated[int | None, typer.Option("--tokens", min=1, help="Tokens to add.")] = None,
    note: Annotated[
        str | None,
        typer.Option("--note", help="Answer to the ticket's BLOCKED line; the next step reads it."),
    ] = None,
    project: Only = None,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Open an approval gate: the approve step, a loop cap, a token cap or a BLOCKED line."""
    with _errors():
        approved = controls.approve_ticket(
            ticket_id, loops=loops, tokens=tokens, project=project, by=by, note=note
        )
        relay.advance_quietly()  # an approval can merge, which can free the next tickets
    if as_json:
        _emit_json(approved)
        return
    running = approved.status.split("/", 1)[1] not in workspace.GATES
    state = "running" if running else approved.status
    typer.echo(_watched(f"ticket {approved.id} approved; {state}", approved.watch))


@app.command("park")
def park_ticket(
    ticket_id: TicketId,
    why: Annotated[str, typer.Option("--why", help="One line: why it waits.")],
    project: Only = None,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Park a ticket; a running one parks after its step."""
    with _errors():
        parked = controls.park_ticket(ticket_id, why, project=project, by=by)
    if as_json:
        _emit_json(parked)
        return
    later = " after its step" if parked.deferred else ""
    typer.echo(f"ticket {parked.id} → in_queue/parked{later}")


@app.command("stop")
def stop_ticket(
    ticket_id: TicketId, project: Only = None, by: By = "unknown", as_json: AsJson = False
) -> None:
    """Kill a ticket's worker now; the ticket fails as stopped."""
    with _errors():
        status_now = controls.stop_ticket(ticket_id, project=project, by=by)
    if as_json:
        typer.echo(json.dumps({"id": ticket_id, "status": status_now}))
        return
    typer.echo(f"ticket {ticket_id} stopped")


@app.command("pause")
def pause(project: Every = None, by: By = "unknown", as_json: AsJson = False) -> None:
    """Start nothing new; running workers finish their step, then pause."""
    with _errors():
        paused = controls.pause(project, by=by)
    if as_json:
        _emit_json(paused)
        return
    typer.echo(f"paused: {paused.running} running finish their step")


@app.command("resume")
def resume(project: Every = None, by: By = "unknown", as_json: AsJson = False) -> None:
    """Clear the pause and restart paused tickets."""
    with _errors():
        resumed = controls.resume(project, by=by)
        relay.advance_quietly()  # the pause held back more than the paused tickets
    if as_json:
        _emit_json(resumed)
        return
    typer.echo(f"resumed {len(resumed.started)}")
    for ticket_id, reason in resumed.skipped.items():
        typer.echo(f"skipped {ticket_id}: {reason}")


@app.command("merge")
def merge_ticket(
    ticket_id: TicketId, project: Only = None, by: By = "unknown", as_json: AsJson = False
) -> None:
    """Rebase the ticket branch, fast-forward the base branch, remove the worktree."""
    with _errors():
        merged = merging.merge_ticket(ticket_id, project=project, by=by)
        relay.advance_quietly()  # a merge can free the next tickets (SP17)
    if as_json:
        _emit_json(merged)
        return
    typer.echo(f"merged {merged.id}: {merged.commits} commits into {merged.base}")
    if merged.decisions:
        plural = "" if merged.decisions == 1 else "s"
        typer.echo(f"DECISIONS.md +{merged.decisions} line{plural}")


loop_app = typer.Typer(
    help="The loop lease: at most one live loop covers a project.", no_args_is_help=True
)
app.add_typer(loop_app, name="loop")


@loop_app.command("claim")
def loop_claim(
    project: Every = None,
    take_over: Annotated[
        bool, typer.Option("--take-over", help="End another conductor's loop on this scope.")
    ] = False,
    as_json: AsJson = False,
) -> None:
    """Take the loop for this conductor; exit 6 while another loop covers the scope."""
    with _errors():
        result = loops.claim(project, take_over=take_over)
    _emit(result, as_json, _watched(f"loop claimed: {result.scope}", result.watch))


@loop_app.command("release")
def loop_release(
    force: Annotated[
        bool, typer.Option("--force", help="Release even with runnable tickets left.")
    ] = False,
    as_json: AsJson = False,
) -> None:
    """End this conductor's loop; refused (exit 1) while tickets are runnable."""
    with _errors():
        result = loops.release(force=force)
    line = f"loop released: {result.scope}" if result.scope else "no loop held here"
    _emit(result, as_json, line)


@loop_app.command("status")
def loop_status(project: Every = None, as_json: AsJson = False) -> None:
    """Live loops on the scope, then its loop_start (ask or auto)."""
    with _errors():
        result = loops.status(project)
    if as_json:
        _emit_json(result)
        return
    lines = [view.line for view in result.leases] or ["no loop running"]
    for line in _capped(lines, "kengash loop status --json", MAX_LINES - 1):
        typer.echo(line)
    typer.echo(f"loop_start: {result.loop_start}")
    if result.relay:
        typer.echo(f"relay on: {', '.join(result.relay)}")


@app.command("wait")
def wait(
    project: Every = None,
    timeout: Annotated[
        float,
        typer.Option("--timeout", min=0, help="Seconds before giving up (exit 3) with progress."),
    ] = 300,
    as_json: AsJson = False,
) -> None:
    """Block until a ticket or a plan review needs the conductor; `idle` when nothing runs;
    on a timeout, one progress line per running ticket."""
    with _errors():
        result = waiting.wait(project, timeout=timeout)
    if as_json:
        _emit_json(result)
    elif result.events:
        # the cursor has moved past every event: capped lines point at `status`, which lists
        # open gates, and queued tickets fold into one line (SP11 final review)
        gates = [event for event in result.events if event.status != "queued"]
        queued = len(result.events) - len(gates)
        tail = [f"queued: {_plural(queued, 'ticket')} ready; run: kengash next"] if queued else []
        lines = _capped(
            [_wait_line(event) for event in gates], "kengash status", MAX_LINES - len(tail)
        )
        for line in [*lines, *tail]:
            typer.echo(line)
    elif result.idle:
        typer.echo("idle")
    if result.timed_out:
        if not as_json:
            lines = [progress.line(item) for item in result.progress]
            for line in _capped(lines, "kengash ps"):
                typer.echo(line)
        typer.echo(f"wait timed out after {timeout:g} s", err=True)
        raise typer.Exit(3)


@app.command("ps")
def show_running(
    project: Every = None,
    one_line: Annotated[
        bool, typer.Option("--line", help="One short line, for a status bar.")
    ] = False,
    as_json: AsJson = False,
) -> None:
    """What every running worker is doing: step, CLI, elapsed, activity, changed files."""
    with _errors():
        found = progress.snapshot(project)
    if as_json:
        typer.echo(json.dumps([dataclasses.asdict(item) for item in found], indent=2))
    elif one_line:
        typer.echo(progress.short(found))
    else:
        lines = [progress.line(item) for item in found] or ["nothing running"]
        for line in _capped(lines, "kengash ps --json"):
            typer.echo(line)


@app.command("logs")
def show_logs(
    ticket_id: TicketId,
    follow: Annotated[
        bool, typer.Option("--follow", "-f", help="Keep printing until the ticket stops.")
    ] = False,
    watch: Annotated[
        bool,
        typer.Option("--watch", help="Follow through gates until the ticket is done (its tab)."),
    ] = False,
    project: Only = None,
    as_json: AsJson = False,
) -> None:
    """What the ticket's workers did, one line per action; -f follows it live."""
    with _errors():
        if watch:
            _viewer(f"kg {ticket_id}")
            with watching.viewing(f"ticket-{ticket_id}"):
                _print_activity(activity.watch(ticket_id, project, until_done=True), as_json)
            _hold(f"{ticket_id} is done; press Enter to close")
            return
        items = (
            activity.watch(ticket_id, project)
            if follow
            else iter(activity.history(ticket_id, project))
        )
        _print_activity(items, as_json)


@app.command("watch")
def watch_board(
    project: Every = None,
    once: Annotated[bool, typer.Option("--once", help="Print one snapshot and exit.")] = False,
    as_json: AsJson = False,
) -> None:
    """One live screen: loops, slots and tokens, running workers, what needs you, the latest
    actions; refreshed every 2 s until Ctrl-C."""
    with _errors():
        if as_json:
            _emit_json(watching.snapshot(project))
            return
        if once or not sys.stdout.isatty():
            for line in watching.lines(watching.snapshot(project)):
                typer.echo(line)
            return
        _viewer(f"kg watch {project}" if project else "kg watch")
        with watching.viewing(f"watch-{project or 'all'}"):
            _live_board(project)


def _live_board(project: str | None) -> None:
    """Redraw the board every REFRESH_S seconds on the terminal's alternate screen."""
    from rich.live import Live

    live = Live(_rendered(project), refresh_per_second=1, screen=True)
    with contextlib.suppress(KeyboardInterrupt), live:
        while True:
            time.sleep(REFRESH_S)
            live.update(_rendered(project))


def _rendered(project: str | None) -> Any:
    """The board in colour: section heads bold, gates yellow, quiet or gone workers red."""
    from rich.console import Group
    from rich.text import Text

    stamp = datetime.now().astimezone().strftime("%H:%M:%S")
    rows = [Text(f"kengash watch · {project or 'all projects'} · {stamp}", style="bold cyan")]
    for line in watching.lines(watching.snapshot(project)):
        if not line.startswith("  "):
            style = "bold"
        elif line.endswith((" · quiet", " · worker gone")) or " · quiet · " in line:
            style = "red"
        elif " → kengash " in line:
            style = "yellow"
        else:
            style = ""
        rows.append(Text(line, style=style, overflow="ellipsis", no_wrap=True))
    return Group(*rows)


def _print_activity(items: Iterator[activity.Activity | None], as_json: bool) -> None:
    for item in items:
        if item is None:
            continue
        if as_json:
            typer.echo(json.dumps(dataclasses.asdict(item), default=str))
        else:
            clock = item.ts.astimezone().strftime("%H:%M:%S") if item.ts else "--:--:--"
            typer.echo(f"{clock} {item.text}")


def _viewer(title: str) -> None:
    """Start a viewer tab: name it, and turn a closed tab (SIGHUP) or a kill (SIGTERM) into
    an orderly exit, so it drops its viewer record on the way out."""
    _title(title)
    if not sys.stdout.isatty():
        return  # piped or under test: the caller's own signal handling stands
    for sig in (signal.SIGTERM, getattr(signal, "SIGHUP", None)):
        if sig is not None:
            signal.signal(sig, _exit_quietly)


def _exit_quietly(signum: int, frame: object) -> None:
    raise SystemExit(0)


def _title(text: str) -> None:
    """Name the terminal tab: every terminal reads this escape, and a shell's own title
    (which Orca and gnome-terminal show) would otherwise replace the opener's."""
    if sys.stdout.isatty():
        sys.stdout.write(f"\x1b]0;{text}\x07")
        sys.stdout.flush()


def _hold(prompt: str) -> None:
    """Keep a viewer tab's last lines on screen until the user presses Enter."""
    if sys.stdin.isatty():
        with contextlib.suppress(EOFError, KeyboardInterrupt):
            input(prompt)


def _watched(line: str, watch: str) -> str:
    """`line`, then where to watch it: a tab, or the command to run (SP13)."""
    return f"{line} (watch: {watch})" if watch else line


def _wait_line(event: waiting.WaitEvent) -> str:
    if event.kind == "plan":
        return (
            f"plan {event.id} round {event.loop}/{event.loop_max}: {event.status}, {event.detail}"
        )
    return f"{event.id} {event.status} loop {event.loop}/{event.loop_max}: {event.detail}"


@ticket_app.command("changes")
def ticket_changes(
    ticket_id: TicketId,
    diff: Annotated[bool, typer.Option("--diff", help="Also print each commit's diff.")] = False,
    project: Only = None,
    as_json: AsJson = False,
) -> None:
    """Files the ticket changed, with the loop, step and model of each commit."""
    with _errors():
        found = changes.ticket_changes(ticket_id, diff=diff, project=project)
    if as_json:
        _emit_json(found)
        return
    for change in found.changes:
        added = "-" if change.added is None else change.added
        removed = "-" if change.removed is None else change.removed
        typer.echo(
            f"{change.path} +{added} -{removed}  loop {change.loop} {change.step} {change.model}"
        )
    if found.diff:
        typer.echo(found.diff)


@ticket_app.command("attach")
def ticket_attach(
    ticket_id: TicketId,
    role: Annotated[str | None, typer.Option("--role", help="Role whose session to open.")] = None,
    tab: Annotated[
        bool, typer.Option("--tab", help="Open the session in a new terminal tab.")
    ] = False,
    project: Only = None,
    as_json: AsJson = False,
) -> None:
    """Print the command that opens a role's live CLI session in the ticket's worktree."""
    with _errors():
        if tab:
            typer.echo(f"attach: {watching.attach_tab(ticket_id, role=role, project=project)}")
            return
        found = changes.attach_command(ticket_id, role=role, project=project)
    if as_json:
        _emit_json(found)
        return
    typer.echo(found.command)


@app.command("forget")
def forget(
    slug: Annotated[str, typer.Argument(help="Project slug from the registry.")],
    yes: Annotated[bool, typer.Option("--yes", help="Forget it without asking.")] = False,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Remove a project from kengash: its plans, tickets, worktrees and .kengash link (the
    store's git history keeps them)."""
    with _errors():
        found = projects.forget_preview(slug)
        what = f"{found.plans} plans, {found.tickets} tickets, {found.worktrees} worktrees"
        if found.dirty:
            what += f" ({found.dirty} with uncommitted changes, which are lost)"
        if not yes:
            if not sys.stdin.isatty():
                raise NeedsUser(f"forget {slug} removes {what}; add --yes to go on")
            typer.echo(f"forget {slug} ({found.path}): removes {what}")
            if input(f"type {slug} to confirm: ").strip() != slug:
                typer.echo(f"kept {slug}")
                raise typer.Exit(1)
        gone = projects.forget_project(slug, by=by)
    if as_json:
        _emit_json(gone)
        return
    typer.echo(f"forgot {slug}: {what} removed; the store's git history keeps them")


agent_app = typer.Typer(help="Agents: add or remove your own roles.", no_args_is_help=True)
app.add_typer(agent_app, name="agent")
Scope = Annotated[
    str | None,
    typer.Option(
        "--project",
        "-p",
        callback=_project,
        help="This project's SETTINGS.md (name or folder); default: the defaults.",
    ),
]


class AgentKind(StrEnum):
    read = "read"
    edit = "edit"
    review = "review"


Fallback = Annotated[
    str | None,
    typer.Option(
        "--fallback", help="CLIs to try next, comma-separated: PROVIDER or PROVIDER/MODEL,…"
    ),
]
SkillName = Annotated[
    str | None, typer.Option("--skill", help="Run this role skill, e.g. review-code.")
]
InstructionsFile = Annotated[
    str | None,
    typer.Option(
        "--instructions-file", help="The agent's own instructions: a file, or - for stdin."
    ),
]


def _list(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _instructions(source: str | None) -> str | None:
    if source is None:
        return None
    if source == "-":
        return _stdin("instructions")
    try:
        return Path(source).read_text(encoding="utf-8")
    except OSError as exc:
        raise UserError(f"cannot read {source}: {exc.strerror or exc}") from exc


@agent_app.command("new")
def agent_new(
    role: Annotated[str, typer.Argument(help="Role name, e.g. perf-reviewer.")],
    kind: Annotated[
        AgentKind, typer.Option("--kind", help="read, edit or review: what its step does.")
    ],
    does: Annotated[str, typer.Option("--does", help="One line: what its step does.")],
    cli: Annotated[
        str, typer.Option("--cli", help="PROVIDER or PROVIDER/MODEL that runs it.")
    ] = "claude",
    step: Annotated[
        str | None, typer.Option("--step", help="Step name; default: the role with _.")
    ] = None,
    workflow: Annotated[
        list[str] | None, typer.Option("--workflow", help="Add the step to this workflow.")
    ] = None,
    after: Annotated[
        str | None, typer.Option("--after", help="Insert after this step; default: last.")
    ] = None,
    send_back: Annotated[
        str | None,
        typer.Option("--send-back", help="Review steps: where a fail sends the ticket."),
    ] = None,
    fallback: Fallback = None,
    skill: SkillName = None,
    instructions_file: InstructionsFile = None,
    project: Scope = None,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Add your own agent: its role, its step and the workflows that run it."""
    with _errors():
        change = agent_config.new_agent(
            role,
            kind=kind.value,
            does=does,
            cli=cli,
            step=step,
            workflows=workflow or [],
            after=after,
            send_back=send_back,
            fallback=_list(fallback),
            skill=skill,
            instructions=_instructions(instructions_file),
            project=project,
            by=by,
        )
    flows = ", ".join(workflow or []) or "no workflow yet"
    skill = f"; skill roles/{role}/SKILL.md" if change.skill_file else ""
    _emit(change, as_json, f"added {role}: step {change.step} in {flows}{skill}")


@agent_app.command("remove")
def agent_remove(
    role: Annotated[str, typer.Argument(help="One of your roles.")],
    project: Scope = None,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Remove one of your agents, its step and every workflow use of it; its skill stays."""
    with _errors():
        change = agent_config.remove_agent(role, project=project, by=by)
    _emit(change, as_json, f"removed {role}")


def _models_for(role: str, given: list[str] | None, project: str | None) -> dict[str, str] | None:
    """The agent's `by_importance` with each `IMPORTANCE=CLI` applied; None when none given."""
    if not given:
        return None
    models = dict(agent_config.show_agent(role, project=project).by_importance)
    for item in given:
        importance, equals, cli = item.partition("=")
        if not equals:
            raise UserError(f"--model-for takes IMPORTANCE=PROVIDER[/MODEL], not {item!r}")
        if cli:
            models[importance] = cli
        else:
            models.pop(importance, None)
    return models


@agent_app.command("edit")
def agent_edit(
    role: Annotated[
        str,
        typer.Argument(
            help="Any agent; a built-in one takes only its CLI, fallbacks and switches."
        ),
    ],
    cli: Annotated[
        str | None, typer.Option("--cli", help="PROVIDER or PROVIDER/MODEL that runs it.")
    ] = None,
    fallback: Fallback = None,
    on: Annotated[bool | None, typer.Option("--on/--off", help="Switch it on or off.")] = None,
    blocking: Annotated[
        bool | None, typer.Option("--blocking/--no-blocking", help="Stop tickets until it passes.")
    ] = None,
    bypass: Annotated[
        bool | None,
        typer.Option(
            "--bypass-permissions/--no-bypass-permissions",
            help="Skip the CLI's permission prompts.",
        ),
    ] = None,
    kind: Annotated[AgentKind | None, typer.Option("--kind", help="read, edit or review.")] = None,
    does: Annotated[str | None, typer.Option("--does", help="One line: what it does.")] = None,
    skill: SkillName = None,
    instructions_file: InstructionsFile = None,
    model_for: Annotated[
        list[str] | None,
        typer.Option(
            "--model-for",
            help="IMPORTANCE=CLI, such as critical=claude/opus, tried first; IMPORTANCE= clears.",
        ),
    ] = None,
    project: Scope = None,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Change an agent: its CLI, fallbacks, switches and per-importance models; for yours also
    its kind, description, skill or own instructions."""
    with _errors():
        patch = agent_config.AgentPatch(
            cli=cli,
            fallback=_list(fallback) if fallback is not None else None,
            on=on,
            blocking=blocking,
            bypass_permissions=bypass,
            kind=kind.value if kind else None,
            does=does,
            skill=skill,
            instructions=_instructions(instructions_file),
            by_importance=_models_for(role, model_for, project),
        )
        change = agent_config.edit_agent(role, patch, project=project, by=by)
    line = f"edited {role}: {', '.join(change.keys) or 'nothing changed'}"
    if change.skill_file:
        line += f"; instructions roles/{role}/SKILL.md"
    _emit(change, as_json, line)


@agent_app.command("copy")
def agent_copy(
    source: Annotated[str, typer.Argument(help="The agent to copy, built-in or yours.")],
    new: Annotated[str, typer.Argument(help="The new agent's role name.")],
    project: Scope = None,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Make an agent of your own from another: its kind, CLI, fallbacks and instructions."""
    with _errors():
        change = agent_config.copy_agent(source, new, project=project, by=by)
    _emit(change, as_json, f"copied {source} to {new}: step {change.step}")


@agent_app.command("show")
def agent_show(
    role: Annotated[str, typer.Argument(help="Any agent.")],
    project: Scope = None,
    as_json: AsJson = False,
) -> None:
    """One agent: its kind, CLI, switches, skill, where it runs and its instructions."""
    with _errors():
        found = agent_config.show_agent(role, project=project)
    if as_json:
        return _emit_json(found)
    yes = {True: "yes", False: "no"}
    used = ", ".join(f"{use.workflow} #{use.position}" for use in found.used_in) or "no workflow"
    cli = found.cli + (f" · fallback: {', '.join(found.fallback)}" if found.fallback else "")
    lines = [
        f"{role} · {'built-in' if found.builtin else 'yours'} · {found.kind} · "
        f"step {found.step} · {'on' if found.on else 'off'}",
        f"cli: {cli}",
        *[f"for {name}: {model}" for name, model in found.by_importance.items()],
        f"blocking: {yes[found.blocking]} · "
        f"skip permission prompts: {yes[found.bypass_permissions]}",
        f"skill: {found.skill}{' (own instructions)' if found.instructions_own else ''}",
        f"used in: {used}",
        f"does: {found.does}",
        "",
        found.instructions.rstrip("\n"),
    ]
    typer.echo("\n".join(lines))


workflow_app = typer.Typer(
    help="Workflows: create, route and edit the step lists.", no_args_is_help=True
)
app.add_typer(workflow_app, name="workflow")


@workflow_app.command("new")
def workflow_new(
    name: Annotated[str, typer.Argument(help="Lowercase letters, digits, - and _.")],
    from_: Annotated[str | None, typer.Option("--from", help="Copy this workflow.")] = None,
    project: Scope = None,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Add a workflow: a copy of another, or one implement step."""
    with _errors():
        change = workflows.new_workflow(name, from_=from_, project=project, by=by)
    _emit(change, as_json, f"added workflow {name}")


@workflow_app.command("rename")
def workflow_rename(
    old: Annotated[str, typer.Argument(help="One of your workflows.")],
    new: Annotated[str, typer.Argument(help="Its new name.")],
    project: Scope = None,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Rename one of your workflows; importance routing follows it."""
    with _errors():
        change = workflows.rename_workflow(old, new, project=project, by=by)
    _emit(change, as_json, f"renamed workflow {old} to {new}")


@workflow_app.command("remove")
def workflow_remove(
    name: Annotated[str, typer.Argument(help="One of your workflows.")],
    project: Scope = None,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Remove one of your workflows that nothing uses."""
    with _errors():
        change = workflows.remove_workflow(name, project=project, by=by)
    _emit(change, as_json, f"removed workflow {name}")


@workflow_app.command("route")
def workflow_route(
    importance: Annotated[str, typer.Argument(help="simple, standard or critical.")],
    workflow: Annotated[str, typer.Argument(help="The workflow its new tickets run.")],
    project: Scope = None,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Choose the workflow new tickets of an importance run."""
    with _errors():
        change = workflows.route(importance, workflow, project=project, by=by)
    _emit(change, as_json, f"{importance} tickets run {workflow}")


@workflow_app.command("set")
def workflow_set(
    name: Annotated[str, typer.Argument(help="The workflow to write.")],
    steps: Annotated[str, typer.Option("--steps", help="Steps in order, comma-separated.")],
    on_fail: Annotated[
        list[str] | None,
        typer.Option("--on-fail", help="STEP=TARGET: a failing review step sends the ticket back."),
    ] = None,
    project: Scope = None,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Write a workflow's steps and send-back edges whole."""
    with _errors():
        edges: dict[str, str] = {}
        for edge in on_fail or []:
            source, sep, target = edge.partition("=")
            if not sep or not source or not target:
                raise UserError(f"--on-fail takes STEP=TARGET, got {edge}")
            edges[source.strip()] = target.strip()
        order = _list(steps)
        change = workflows.set_workflow(name, order, edges, project=project, by=by)
    _emit(change, as_json, f"set workflow {name}: {' → '.join(order)}")


skills_app = typer.Typer(help="Skills: lint, install, eval and show.", no_args_is_help=True)
app.add_typer(skills_app, name="skills")


@skills_app.command("show")
def skills_show(
    name: Annotated[str, typer.Argument(help="The skill, e.g. ticket.")],
    agent: Annotated[
        str | None,
        typer.Option("--agent", help="claude, codex or antigravity; default: the calling agent."),
    ] = None,
) -> None:
    """Print a skill as installed for the calling agent: how one skill hands over to the next."""
    with _errors():
        text = skills.show(
            name,
            agent=agent or conductors.conductor().agent,
            cli_name=skills.invoked_name(sys.argv[0]),
        )
    typer.echo(text, nl=False)


def _command_tree() -> set[str]:
    """Every command name, plus `<group> <command>` for the commands of each group."""
    root: Any = typer.main.get_command(app)  # typer's vendored click: groups have `commands`
    names: set[str] = set()
    for name, command in root.commands.items():
        names.add(name)
        names |= {f"{name} {sub}" for sub in getattr(command, "commands", {})}
    return names


@skills_app.command("lint")
def skills_lint(
    paths: Annotated[
        list[Path] | None,
        typer.Argument(help="SKILL.md files or folders; default: every packaged skill."),
    ] = None,
    as_json: AsJson = False,
) -> None:
    """Check skills against the writing standard; prints problems only."""
    with _errors():
        problems = skills.lint_skills(paths or [], commands=_command_tree())
    if as_json:
        typer.echo(json.dumps([dataclasses.asdict(p) for p in problems], indent=2))
    else:
        for problem in problems:
            typer.echo(f"{problem.path}: {problem.message}")
    if problems:
        raise typer.Exit(1)


@skills_app.command("install")
def skills_install(
    agent: Annotated[
        str, typer.Option("--agent", help="claude, codex, antigravity (agy); comma-separated.")
    ],
    global_: Annotated[
        bool, typer.Option("--global", help="Install for every project, in your home folder.")
    ] = False,
    path: Annotated[
        Path | None, typer.Option("--path", help="A folder in the repo; default: this folder.")
    ] = None,
    cli_name: Annotated[
        str,
        typer.Option("--cli-name", help="The command the skills call: kengash, or a full path."),
    ] = "kengash",
    yes: Annotated[bool, typer.Option("--yes", help="Replace skills that differ.")] = False,
    as_json: AsJson = False,
) -> None:
    """Install the skills into your agents' skills folders; never replaces an edited one
    without --yes."""
    with _errors():
        result = skills.install_skills(
            agent.split(","), global_=global_, path=path or Path.cwd(), cli_name=cli_name, yes=yes
        )
    if as_json:
        typer.echo(
            json.dumps(
                {**dataclasses.asdict(result), "needs_yes": result.needs_yes}, default=str, indent=2
            )
        )
    else:
        lines = [
            f"{e.agent} {e.name}: {e.state} → {e.folder}" + (f" ({e.note})" if e.note else "")
            for e in result.entries
        ]
        for line in _capped(lines, "kengash skills install --json"):
            typer.echo(line)
        for note in result.notes:
            typer.echo(f"note: {note}")
        for diff in result.diffs.values():
            typer.echo(diff, nl=False)
    if result.needs_yes:
        count = _plural(len(result.diffs), "skill")
        typer.echo(
            f"{count} differ from the installed copies; rerun with --yes to replace them", err=True
        )
        raise typer.Exit(5)


@skills_app.command("eval")
def skills_eval(
    skill: Annotated[str | None, typer.Argument(help="The skill whose scenarios to run.")] = None,
    all_: Annotated[bool, typer.Option("--all", help="Every skill's scenarios.")] = False,
    agent: Annotated[
        str | None, typer.Option("--agent", help="claude, codex, antigravity; default: all usable.")
    ] = None,
    model: Annotated[
        str | None, typer.Option("--model", help="Conductor model; default: the cheapest.")
    ] = None,
    baseline: Annotated[
        bool, typer.Option("--baseline", help="Run without installing the skills (RED).")
    ] = False,
    folder: Annotated[
        Path | None, typer.Option("--dir", help="Scenario folder; default: the checkout's evals/.")
    ] = None,
    keep: Annotated[
        Path | None, typer.Option("--keep", help="Write each run's store and transcripts here.")
    ] = None,
    as_json: AsJson = False,
) -> None:
    """Replay eval scenarios headless on real agents; spends subscription quota."""
    with _errors():
        if skill is None and not all_:
            raise UserError("name a skill, or pass --all")
        runs, base = evals.run_evals(
            None if all_ else skill,
            agents_=agent.split(",") if agent else None,
            model=model,
            baseline=baseline,
            root=folder or evals.EVALS_DIR,
            keep=keep,
        )
    if as_json:
        typer.echo(json.dumps([dataclasses.asdict(run) for run in runs], default=str, indent=2))
    else:
        for run in runs:
            verdict = "pass" if run.passed else f"fail: {run.failure}"
            typer.echo(f"{run.name} {run.agent}: {verdict}")
        typer.echo(f"transcripts: {base}")
    if not all(run.passed for run in runs):
        raise typer.Exit(1)


ui_app = typer.Typer(help="The local web UI.", no_args_is_help=True)
app.add_typer(ui_app, name="ui")


@ui_app.command("open")
def ui_open(
    no_browser: Annotated[
        bool, typer.Option("--no-browser", help="Print the link without opening it.")
    ] = False,
    as_json: AsJson = False,
) -> None:
    """Start the UI, or reuse the running one, and open it in the browser."""
    with _errors():
        server = ui_server.open_ui(browser=not no_browser)
    if as_json:
        _emit_json(server)
    else:
        typer.echo(server.url)


@ui_app.command("stop")
def ui_stop() -> None:
    """Stop the UI server."""
    with _errors():
        stopped = ui_server.stop_ui()
    typer.echo("stopped" if stopped else "not running")
