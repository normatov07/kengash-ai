"""Custom agents (SP6 spec decisions 5-7): a user's role, its step and the workflows that run
it, written in one validated save of one scope's SETTINGS.md, then a starter role skill."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from super_harness import settings
from super_harness.model import STEP_ROLES, Event, Folder, Settings, StepKind, UserError
from super_harness.ops import records, skills
from super_harness.store.files import atomic_write
from super_harness.store.locks import locked
from super_harness.store.paths import StorePaths

BUILTIN_ROLES = frozenset(role for role in STEP_ROLES.values() if role)
STARTER_HEAD = """---
name: {role}
description: Use when you are the {role} on a super-harness ticket.
metadata: {{source: user}}
---
# {title}

{does}

"""
# What each kind's starter tells the CLI to do; the reply matches the step's output schema
STARTER_STEPS = {
    "read": (
        "1. Read the ticket's Scope, Acceptance and Handoff, and the code they name. "
        "Edit nothing.\n"
        "2. Note what the next step needs: findings, decisions, the files and lines involved.\n"
        "3. Reply with JSON: `summary` in one line and `handoff` for the next step.\n"
    ),
    "edit": (
        "1. Read the ticket's Scope, Acceptance, Handoff and Findings.\n"
        "2. Make the change in this worktree, with tests where behaviour changes. "
        "Do not commit; harness commits.\n"
        "3. Run the project's tests when you can, and say what you ran.\n"
        "4. Reply with JSON: `summary` in one line and `handoff` for the next step.\n"
    ),
    "review": (
        "1. Read the changes: `git log --oneline` lists the ticket's commits (subjects start "
        "with `hrn(<ticket id>)`), and `git show <commit>` shows each. Edit nothing.\n"
        "2. Check them against the instruction above.\n"
        "3. Fail only for real problems; rate each finding high, medium or low.\n"
        "4. Reply with JSON: `verdict`, `summary` in one line, and `findings` with `severity`, "
        "`file`, `line`, `issue` and `fix`.\n"
    ),
}


@dataclass
class AgentChange:
    project: str | None
    role: str
    step: str
    keys: list[str] = field(default_factory=list)
    skill_file: str = ""  # the starter written; empty when a skill already existed


def new_agent(
    role: str,
    *,
    kind: StepKind,
    does: str,
    cli: str = "claude",
    step: str | None = None,
    workflows: Sequence[str] = (),
    after: str | None = None,
    send_back: str | None = None,
    project: str | None,
    by: str,
) -> AgentChange:
    """Add `role` and its step to one scope, insert the step into each named workflow after
    `after` (default: before `approve`, else last), and for a review step add the `on_fail`
    edge to `send_back` (default `implement` when the workflow has it)."""
    paths = StorePaths.default()
    if project is not None:
        records.scope(paths, project)
    name = step or role.replace("-", "_")
    if send_back is not None and kind != "review":
        raise UserError("only a review step sends a ticket back")
    with locked(paths.locks / "settings.lock"):  # read, change and write as one edit
        resolved = settings.load(paths, project)
        if role in resolved.agents:
            raise UserError(f"agent {role} exists; pick another name")
        if name in resolved.step_names():
            raise UserError(f"step {name} exists; pass another step name")
        changes: dict[str, Any] = {
            f"agents.{role}": {"on": True, "cli": cli, "skill": role},
            f"steps.{name}": {"role": role, "kind": kind, "does": does},
        }
        for flow in workflows:
            changes[f"workflows.{flow}"] = _with_step(resolved, flow, name, kind, after, send_back)
        keys = settings.set_values(paths, project, changes)
        written = _starter(paths, project, role, kind, does)
    event = Event(type="settings.changed", project=project, keys=keys, by=by)
    records.record(paths, f"harness: agent new {role}", event)
    return AgentChange(project, role, name, keys, str(written) if written else "")


def remove_agent(role: str, *, project: str | None, by: str) -> AgentChange:
    """Remove a user's role from one scope: the agent, its steps, those steps in every
    workflow and every `on_fail` edge naming them. The role skill file stays."""
    paths = StorePaths.default()
    slugs = records.scope(paths, project)
    if role in BUILTIN_ROLES:
        raise UserError(f"{role} is a built-in role; switch it off instead")
    with locked(paths.locks / "settings.lock"):  # read, change and write as one edit
        resolved = settings.load(paths, project)
        if role not in resolved.agents:
            raise UserError(f"no agent {role}")
        own = settings.scope_keys(paths, project)
        if not any(key == f"agents.{role}" or key.startswith(f"agents.{role}.") for key in own):
            where = "the defaults" if project is None else project
            raise UserError(f"agent {role} is not set in {where}; remove it where it is set")
        steps = [name for name, step in resolved.steps.items() if step.role == role]
        for slug in slugs:
            for doc in records.project_tickets(paths, slug).values():
                ticket = doc.meta
                if ticket.folder is Folder.in_process and ticket.step in steps:
                    raise UserError(f"ticket {ticket.id} is at step {ticket.step}; move it first")
        changes: dict[str, Any] = {f"agents.{role}": None}
        changes |= {f"steps.{name}": None for name in steps}
        for flow_name, flow in resolved.workflows.items():
            edges = {k: v for k, v in flow.on_fail.items() if k not in steps and v not in steps}
            kept = [name for name in flow.steps if name not in steps]
            if kept != flow.steps or edges != flow.on_fail:
                changes[f"workflows.{flow_name}"] = {"steps": kept, "on_fail": edges}
        keys = settings.set_values(paths, project, changes)
    event = Event(type="settings.changed", project=project, keys=keys, by=by)
    records.record(paths, f"harness: agent remove {role}", event)
    return AgentChange(project, role, ", ".join(steps), keys)


def _with_step(
    resolved: Settings,
    flow: str,
    step: str,
    kind: StepKind,
    after: str | None,
    send_back: str | None,
) -> dict[str, Any]:
    """Workflow `flow` with `step` inserted, as the whole value `workflows.<flow>` takes."""
    found = resolved.workflows.get(flow)
    if found is None:
        raise UserError(f"unknown workflow {flow}; known: {', '.join(resolved.workflows)}")
    steps = list(found.steps)
    if after is not None and after not in steps:
        raise UserError(f"workflow {flow} has no step {after}")
    at = steps.index(after) + 1 if after else len(steps)
    if after is None and "approve" in steps:
        at = steps.index("approve")
    steps.insert(at, step)
    edges = dict(found.on_fail)
    target = send_back
    if target is None and kind == "review" and "implement" in steps:
        target = "implement"
    if target is not None:
        if target not in steps:
            raise UserError(f"workflow {flow} has no step {target}")
        edges[step] = target
    return {"steps": steps, "on_fail": edges}


def _starter(
    paths: StorePaths, project: str | None, role: str, kind: StepKind, does: str
) -> Path | None:
    """Write the role's starter skill into the scope's `roles/`, unless a skill by that
    name is already on the lookup path."""
    if skills.role_file(paths, project, role) is not None:
        return None
    root = paths.defaults if project is None else paths.project(project).root
    path = root / "roles" / role / "SKILL.md"
    title = role.replace("-", " ").capitalize()
    text = STARTER_HEAD.format(role=role, title=title, does=does) + STARTER_STEPS[kind]
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, text)
    return path
