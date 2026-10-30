"""Agents (SP6 spec decisions 5-7, SP10 spec §4): a user's role, its step and the workflows
that run it; edits, copies and descriptions of any agent. Every change is one validated save
of one scope's SETTINGS.md, then the role skill file when the agent has its own."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kengash_ai import settings
from kengash_ai.model import (
    STEP_ROLES,
    Event,
    Folder,
    Settings,
    StepKind,
    UserError,
    split_cli,
)
from kengash_ai.model.settings import SkillCaps
from kengash_ai.ops import records, skills
from kengash_ai.store.files import atomic_write
from kengash_ai.store.frontmatter import split_frontmatter
from kengash_ai.store.locks import locked
from kengash_ai.store.paths import StorePaths

BUILTIN_ROLES = frozenset(role for role in STEP_ROLES.values() if role)
BUILTIN_STEPS = {role: step for step, role in STEP_ROLES.items() if role}
# what each built-in agent does, in a line: the UI's and `kengash agent show`'s description
BUILTIN_DOES = {
    "planner": "Writes the ticket's implementation plan.",
    "plan-reviewer": "Gives a second opinion on the plan before any code is written.",
    "implementer": "Writes the code in a worktree of its own.",
    "code-reviewer": "Reviews the ticket's changes, the diff only by default.",
    "security-reviewer": "Checks secrets, authz and the dependency surface.",
    "test-runner": "Runs project.test_cmd, with no model call.",
    "doc-writer": "Keeps the docs in step with the code.",
}
HEADER = """---
name: {role}
description: Use when you are the {role} on a kengash_ai ticket.
metadata: {{source: user}}
---
"""
STARTER_HEAD = "# {title}\n\n{does}\n\n"
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
        "Do not commit; kengash commits.\n"
        "3. Run the project's tests when you can, and say what you ran.\n"
        "4. Reply with JSON: `summary` in one line and `handoff` for the next step.\n"
    ),
    "review": (
        "1. Read the changes: `git log --oneline` lists the ticket's commits (subjects start "
        "with `kg(<ticket id>)`), and `git show <commit>` shows each. Edit nothing.\n"
        "2. Check them against the instruction above.\n"
        "3. Fail only for real problems; rate each finding high, medium or low.\n"
        "4. Reply with JSON: `verdict`, `summary` in one line, and `findings` with `severity`, "
        "`file`, `line`, `issue` and `fix`.\n"
    ),
}
FIXED = ("kind", "does", "skill", "instructions")  # what a built-in agent keeps


@dataclass
class AgentChange:
    project: str | None
    role: str
    step: str
    keys: list[str] = field(default_factory=list)
    skill_file: str = ""  # the role skill written; empty when none was


@dataclass
class AgentPatch:
    """An edit of one agent; a field left None stays as it is."""

    cli: str | None = None
    fallback: list[str] | None = None
    on: bool | None = None
    blocking: bool | None = None
    bypass_permissions: bool | None = None
    kind: StepKind | None = None
    does: str | None = None
    skill: str | None = None
    instructions: str | None = None


@dataclass
class UsedIn:
    workflow: str
    position: int  # 1-based, in the workflow's step list


@dataclass
class AgentDetail:
    role: str
    builtin: bool
    kind: str | None  # read, edit, review; check for the test runner
    step: str | None
    does: str
    cli: str
    provider: str
    model: str
    fallback: list[str]
    on: bool
    blocking: bool
    bypass_permissions: bool
    skill: str
    instructions_own: bool  # the agent's own text in the store, editable
    instructions: str
    used_in: list[UsedIn] = field(default_factory=list)
    tokens: int = 0


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
    fallback: Sequence[str] = (),
    skill: str | None = None,
    instructions: str | None = None,
    project: str | None,
    by: str,
) -> AgentChange:
    """Add `role` and its step to one scope, insert the step into each named workflow after
    `after` (default: before `approve`, else last), and for a review step add the `on_fail`
    edge to `send_back` (default `implement` when the workflow has it). The agent runs
    `skill`, or its own `instructions`, or else its kind's starter."""
    paths = StorePaths.default()
    if project is not None:
        records.scope(paths, project)
    name = step or role.replace("-", "_")
    if send_back is not None and kind != "review":
        raise UserError("only a review step sends a ticket back")
    if skill is not None and instructions is not None:
        raise UserError("pass a skill or instructions, not both")
    text = instructions
    if text is None and skill is None and skills.role_file(paths, project, role) is None:
        text = STARTER_HEAD.format(title=role.replace("-", " ").capitalize(), does=does)
        text += STARTER_STEPS[kind]
    with locked(paths.locks / "settings.lock"):  # read, change and write as one edit
        resolved = settings.load(paths, project)
        if role in resolved.agents:
            raise UserError(f"agent {role} exists; pick another name")
        if name in resolved.step_names():
            raise UserError(f"step {name} exists; pass another step name")
        if skill is not None:
            _known_skill(paths, project, skill)
        if text is not None:
            _check_instructions(role, text, resolved.skill)
        agent: dict[str, Any] = {"on": True, "cli": cli, "skill": skill or role}
        if fallback:
            agent["fallback"] = list(fallback)
        changes: dict[str, Any] = {
            f"agents.{role}": agent,
            f"steps.{name}": {"role": role, "kind": kind, "does": does},
        }
        for flow in workflows:
            changes[f"workflows.{flow}"] = _with_step(resolved, flow, name, kind, after, send_back)
        keys = settings.set_values(paths, project, changes)
        written = _write_instructions(paths, project, role, text) if text is not None else None
    _record(paths, project, f"agent new {role}", keys, by)
    return AgentChange(project, role, name, keys, str(written) if written else "")


def edit_agent(role: str, patch: AgentPatch, *, project: str | None, by: str) -> AgentChange:
    """Change one agent in one scope. A built-in agent takes only its CLI, fallbacks and
    switches; a user's agent also its kind, description and skill or own instructions.
    Leaving the review kind drops the step's send-back edges."""
    paths = StorePaths.default()
    if project is not None:
        records.scope(paths, project)
    if patch.skill is not None and patch.instructions is not None:
        raise UserError("pass a skill or instructions, not both")
    with locked(paths.locks / "settings.lock"):
        resolved = settings.load(paths, project)
        if role not in resolved.agents:
            raise UserError(f"no agent {role}")
        if role in BUILTIN_ROLES:
            for name in FIXED:
                if getattr(patch, name) is not None:
                    raise UserError(
                        f"{role} is a built-in agent; its {name} is fixed; "
                        "copy it to change what it does"
                    )
        if patch.instructions is not None:
            _check_instructions(role, patch.instructions, resolved.skill)
        if patch.skill is not None:
            _known_skill(paths, project, patch.skill)
        changes: dict[str, Any] = {}
        for key in ("cli", "fallback", "on", "blocking", "bypass_permissions", "skill"):
            value = getattr(patch, key)
            if value is not None:
                changes[f"agents.{role}.{key}"] = value
        if patch.instructions is not None:
            changes[f"agents.{role}.skill"] = role
        step = _own_step(resolved, role)
        if step is not None:
            if patch.kind is not None:
                changes[f"steps.{step}.kind"] = patch.kind
                if patch.kind != "review":
                    changes |= _without_edges_from(resolved, step)
            if patch.does is not None:
                changes[f"steps.{step}.does"] = patch.does
        keys = settings.set_values(paths, project, changes)
        written = None
        if patch.instructions is not None:
            written = _write_instructions(paths, project, role, patch.instructions)
    _record(paths, project, f"agent edit {role}", keys, by)
    return AgentChange(project, role, step or "", keys, str(written) if written else "")


def copy_agent(source: str, new: str, *, project: str | None, by: str) -> AgentChange:
    """A user's agent made from `source`: its kind, CLI, fallbacks and description, and its
    own instructions starting from the source's skill text. It joins no workflow."""
    paths = StorePaths.default()
    if project is not None:
        records.scope(paths, project)
    resolved = settings.load(paths, project)
    if source not in resolved.agents:
        raise UserError(f"no agent {source}")
    if new in resolved.agents:
        raise UserError(f"agent {new} exists; pick another name")
    detail = describe(paths, resolved, project, source)
    if detail.kind not in ("read", "edit", "review"):
        raise UserError(f"{source} cannot be copied: it runs a shell check, not a model")
    kind: StepKind = detail.kind  # type: ignore[assignment]  # narrowed by the check above
    return new_agent(
        new,
        kind=kind,
        does=detail.does,
        cli=detail.cli,
        fallback=detail.fallback,
        instructions=detail.instructions,
        project=project,
        by=by,
    )


def describe(paths: StorePaths, resolved: Settings, project: str | None, role: str) -> AgentDetail:
    """Everything about one agent of a resolved scope; `tokens` is the caller's to fill."""
    agent = resolved.agents[role]
    builtin = role in BUILTIN_ROLES
    step = BUILTIN_STEPS.get(role) if builtin else _own_step(resolved, role)
    kind = resolved.kind_of(step) if step else None
    custom = resolved.steps.get(step) if step else None
    does = BUILTIN_DOES.get(role, "") if builtin else (custom.does if custom else "")
    provider, model = split_cli(agent.cli)
    path = skills.role_file(paths, project, agent.skill)
    instructions = _body(path) if path is not None else ""
    own = not builtin and agent.skill == role and path is not None
    used_in = [
        UsedIn(name, flow.steps.index(step) + 1)
        for name, flow in resolved.workflows.items()
        if step in flow.steps
    ]
    return AgentDetail(
        role,
        builtin,
        kind,
        step,
        does,
        agent.cli,
        provider,
        model or "default",
        list(agent.fallback),
        agent.on,
        agent.blocking,
        agent.bypass_permissions,
        agent.skill,
        own,
        instructions,
        used_in,
    )


def show_agent(role: str, *, project: str | None) -> AgentDetail:
    """`kengash agent show`: one agent of the defaults or a project."""
    paths = StorePaths.default()
    if project is not None:
        records.scope(paths, project)
    resolved = settings.load(paths, project)
    if role not in resolved.agents:
        raise UserError(f"no agent {role}")
    return describe(paths, resolved, project, role)


def instruction_caps(role: str, caps: SkillCaps) -> tuple[int, int]:
    """The lines and words an agent's own instructions may hold: the skill caps less the
    header kengash writes above them."""
    header = HEADER.format(role=role)
    return caps.max_lines - len(header.splitlines()), caps.max_words - len(header.split())


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
    _record(paths, project, f"agent remove {role}", keys, by)
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


def _without_edges_from(resolved: Settings, step: str) -> dict[str, Any]:
    """Every workflow that sends back from `step`, whole, without that edge."""
    return {
        f"workflows.{name}": {
            "steps": list(flow.steps),
            "on_fail": {k: v for k, v in flow.on_fail.items() if k != step},
        }
        for name, flow in resolved.workflows.items()
        if step in flow.on_fail
    }


def _own_step(resolved: Settings, role: str) -> str | None:
    found = [name for name, step in resolved.steps.items() if step.role == role]
    return found[0] if found else None


def _known_skill(paths: StorePaths, project: str | None, skill: str) -> None:
    if skills.role_file(paths, project, skill) is None:
        raise UserError(f"no role skill {skill}")


def _check_instructions(role: str, text: str, caps: SkillCaps) -> None:
    if not text.strip():
        raise UserError("instructions are empty")
    lines, words = instruction_caps(role, caps)
    if len(text.splitlines()) > lines:
        raise UserError(f"instructions have {len(text.splitlines())} lines; the cap is {lines}")
    if len(text.split()) > words:
        raise UserError(f"instructions have {len(text.split())} words; the cap is {words}")


def _write_instructions(paths: StorePaths, project: str | None, role: str, text: str) -> Path:
    """The agent's own role skill in the scope's `roles/`: kengash's header, then `text`."""
    root = paths.defaults if project is None else paths.project(project).root
    path = root / "roles" / role / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, HEADER.format(role=role) + text + ("" if text.endswith("\n") else "\n"))
    return path


def _body(path: Path) -> str:
    try:
        return split_frontmatter(path.read_text(encoding="utf-8"))[1]
    except UserError:
        return path.read_text(encoding="utf-8")  # a hand-written file without frontmatter


def _record(paths: StorePaths, project: str | None, what: str, keys: list[str], by: str) -> None:
    event = Event(type="settings.changed", project=project, keys=keys, by=by)
    records.record(paths, f"kengash: {what}", event)
