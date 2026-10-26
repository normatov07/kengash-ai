"""Command-line entry point for `harness` (alias `hrn`)."""

import dataclasses
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import typer

from kengash_ai import __version__
from kengash_ai.model import Folder, HarnessError, PlanMode, UserError
from kengash_ai.ops import (
    agent_config,
    changes,
    compaction,
    controls,
    evals,
    merging,
    plans,
    projects,
    queue,
    reviews,
    skills,
    status,
    tickets,
    ui_server,
    waiting,
    workspace,
)

app = typer.Typer(
    name="kengash",
    help="Run many projects at once with subscription coding-agent CLIs.",
    no_args_is_help=True,
    add_completion=False,
)

AsJson = Annotated[bool, typer.Option("--json", help="Print machine-readable JSON.")]


def _require_posix() -> None:
    """harness drives process groups and folder links: Linux and macOS (system spec §1)."""
    if sys.platform == "win32":
        typer.echo("harness runs on Linux and macOS; on Windows use WSL", err=True)
        raise typer.Exit(4)


DEPRECATED = "harness is now kengash; the harness and hrn names stop working in 0.3.0"


def legacy() -> None:
    """The 0.1.0 entry points, `harness` and `hrn`: one stderr line, then the same app, so
    `--json` output stays clean (SP8 spec decision 1)."""
    print(DEPRECATED, file=sys.stderr)
    app()


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
    """Turn a harness error into one stderr line and the spec's exit code."""
    try:
        yield
    except HarnessError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(error.exit_code) from None


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
    """Check projects, links, documents, providers and repo trust; --fix repairs links."""
    with _errors():
        report = projects.doctor(fix=fix, scan=scan)
    if as_json:
        _emit_json(report)
    else:
        for problem in report.problems:
            prefix = f"{problem.slug}: " if problem.slug else ""
            typer.echo(prefix + ("warning: " if problem.warning else "") + problem.message)
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
        for line in _capped([*lines, *result.findings], f"harness plan show {result.id}"):
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
        lines = [f"started {s.id} {s.step}→{s.provider}" for s in result.started]
        lines += [f"skipped {tid}: {reason}" for tid, reason in result.skipped.items()]
        for line in _capped(lines, "harness run --json"):
            typer.echo(line)
    if not result.started:
        raise typer.Exit(1)


@app.command("approve")
def approve_ticket(
    ticket_id: TicketId,
    loops: Annotated[int | None, typer.Option("--loops", min=1, help="Loops to add.")] = None,
    tokens: Annotated[int | None, typer.Option("--tokens", min=1, help="Tokens to add.")] = None,
    project: Only = None,
    by: By = "unknown",
    as_json: AsJson = False,
) -> None:
    """Open an approval gate: the approve step, a loop cap or a token cap."""
    with _errors():
        approved = controls.approve_ticket(
            ticket_id, loops=loops, tokens=tokens, project=project, by=by
        )
    if as_json:
        _emit_json(approved)
        return
    running = approved.status.split("/", 1)[1] not in workspace.GATES
    typer.echo(f"ticket {approved.id} approved; {'running' if running else approved.status}")


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
    if as_json:
        _emit_json(resumed)
        return
    typer.echo(f"resumed {len(resumed.started)}")


@app.command("merge")
def merge_ticket(
    ticket_id: TicketId, project: Only = None, by: By = "unknown", as_json: AsJson = False
) -> None:
    """Rebase the ticket branch, fast-forward the base branch, remove the worktree."""
    with _errors():
        merged = merging.merge_ticket(ticket_id, project=project, by=by)
    if as_json:
        _emit_json(merged)
        return
    typer.echo(f"merged {merged.id}: {merged.commits} commits into {merged.base}")


@app.command("wait")
def wait(
    project: Every = None,
    timeout: Annotated[
        float, typer.Option("--timeout", min=0, help="Seconds before giving up (exit 3).")
    ] = 540,
    as_json: AsJson = False,
) -> None:
    """Block until a ticket or a plan review needs the conductor; `idle` when nothing runs."""
    with _errors():
        result = waiting.wait(project, timeout=timeout)
    if as_json:
        _emit_json(result)
    elif result.events:
        lines = [_wait_line(event) for event in result.events]
        for line in _capped(lines, "harness wait --json"):
            typer.echo(line)
    elif result.idle:
        typer.echo("idle")
    if result.timed_out:
        typer.echo(f"wait timed out after {timeout:g} s", err=True)
        raise typer.Exit(3)


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
    project: Only = None,
    as_json: AsJson = False,
) -> None:
    """Print the command that opens a role's live CLI session in the ticket's worktree."""
    with _errors():
        found = changes.attach_command(ticket_id, role=role, project=project)
    if as_json:
        _emit_json(found)
        return
    typer.echo(found.command)


agent_app = typer.Typer(help="Agents: add or remove your own roles.", no_args_is_help=True)
app.add_typer(agent_app, name="agent")
Scope = Annotated[
    str | None,
    typer.Option("--project", "-p", help="This project's SETTINGS.md; default: the defaults."),
]


class AgentKind(StrEnum):
    read = "read"
    edit = "edit"
    review = "review"


@agent_app.command("new")
def agent_new(
    role: Annotated[str, typer.Argument(help="Role name, e.g. perf-reviewer.")],
    kind: Annotated[
        AgentKind, typer.Option("--kind", help="read, edit or review: what its step does.")
    ],
    does: Annotated[str, typer.Option("--does", help="One line: what its step does.")],
    cli: Annotated[str, typer.Option("--cli", help="PROVIDER[/MODEL] that runs it.")] = "claude",
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


skills_app = typer.Typer(help="Skills: lint, install and eval.", no_args_is_help=True)
app.add_typer(skills_app, name="skills")


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
    ] = "harness",  # becomes kengash once the skills call kengash (SP8 Task 6)
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
        lines = [f"{e.agent} {e.name}: {e.state} → {e.folder}" for e in result.entries]
        for line in _capped(lines, "harness skills install --json"):
            typer.echo(line)
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
