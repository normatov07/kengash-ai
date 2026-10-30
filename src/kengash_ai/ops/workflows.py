"""Workflows (SP10 spec §4.5-4.6): create, copy, rename and remove a workflow, route an
importance to one, and set one's steps and edges. Each change is one validated save of one
scope's SETTINGS.md, journaled as `settings.changed` and committed."""

from dataclasses import dataclass, field
from typing import Any

from kengash_ai import settings
from kengash_ai.model import IMPORTANCES, Event, Folder, Settings, UserError
from kengash_ai.model.settings import WORKFLOW_NAME
from kengash_ai.ops import records
from kengash_ai.store.locks import locked
from kengash_ai.store.paths import StorePaths

BLANK: dict[str, Any] = {"steps": ["implement"], "on_fail": {}}


@dataclass
class WorkflowChange:
    project: str | None
    name: str
    keys: list[str] = field(default_factory=list)


def new_workflow(
    name: str, *, from_: str | None = None, project: str | None, by: str
) -> WorkflowChange:
    """A new workflow: a copy of `from_`, or one implement step."""

    def change(paths: StorePaths, resolved: Settings) -> dict[str, Any]:
        _check_name(name)
        if name in resolved.workflows:
            raise UserError(f"workflow {name} exists")
        return {f"workflows.{name}": _whole(resolved, from_) if from_ else BLANK}

    return _save(project, name, f"workflow new {name}", by, change)


def rename_workflow(old: str, new: str, *, project: str | None, by: str) -> WorkflowChange:
    """Rename a workflow of the user's; routing entries that named it follow."""

    def change(paths: StorePaths, resolved: Settings) -> dict[str, Any]:
        _check_name(new)
        _changeable(paths, resolved, project, old)
        if new in resolved.workflows:
            raise UserError(f"workflow {new} exists")
        changes: dict[str, Any] = {
            f"workflows.{old}": None,
            f"workflows.{new}": _whole(resolved, old),
        }
        for importance in IMPORTANCES:
            if resolved.workflow_for(importance) == old:
                changes[f"routing.{importance}"] = new
        return changes

    return _save(project, new, f"workflow rename {old} {new}", by, change)


def remove_workflow(name: str, *, project: str | None, by: str) -> WorkflowChange:
    """Remove a workflow of the user's that no importance routes to."""

    def change(paths: StorePaths, resolved: Settings) -> dict[str, Any]:
        _changeable(paths, resolved, project, name)
        for importance in IMPORTANCES:
            if resolved.workflow_for(importance) == name:
                raise UserError(
                    f"workflow {name} is routed from {importance}; route it elsewhere first"
                )
        return {f"workflows.{name}": None}

    return _save(project, name, f"workflow remove {name}", by, change)


def route(importance: str, workflow: str, *, project: str | None, by: str) -> WorkflowChange:
    """Send new tickets of `importance` to `workflow`."""

    def change(paths: StorePaths, resolved: Settings) -> dict[str, Any]:
        if importance not in IMPORTANCES:
            known = ", ".join(IMPORTANCES)
            raise UserError(f"unknown importance {importance}; known: {known}")
        return {f"routing.{importance}": workflow}

    return _save(project, workflow, f"workflow route {importance} {workflow}", by, change)


def set_workflow(
    name: str, steps: list[str], on_fail: dict[str, str], *, project: str | None, by: str
) -> WorkflowChange:
    """Write a workflow's steps and send-back edges whole."""

    def change(paths: StorePaths, resolved: Settings) -> dict[str, Any]:
        _check_name(name)
        return {f"workflows.{name}": {"steps": list(steps), "on_fail": dict(on_fail)}}

    return _save(project, name, f"workflow set {name}", by, change)


def _save(project: str | None, name: str, what: str, by: str, change: Any) -> WorkflowChange:
    paths = StorePaths.default()
    if project is not None:
        records.scope(paths, project)
    with locked(paths.locks / "settings.lock"):  # read, change and write as one edit
        resolved = settings.load(paths, project)
        keys = settings.set_values(paths, project, change(paths, resolved))
    event = Event(type="settings.changed", project=project, keys=keys, by=by)
    records.record(paths, f"kengash: {what}", event)
    return WorkflowChange(project, name, keys)


def _check_name(name: str) -> None:
    if not WORKFLOW_NAME.fullmatch(name):
        raise UserError(f"workflow name must match {WORKFLOW_NAME.pattern}")


def _whole(resolved: Settings, name: str) -> dict[str, Any]:
    found = resolved.workflows.get(name)
    if found is None:
        raise UserError(f"unknown workflow {name}; known: {', '.join(resolved.workflows)}")
    return {"steps": list(found.steps), "on_fail": dict(found.on_fail)}


def _changeable(paths: StorePaths, resolved: Settings, project: str | None, name: str) -> None:
    """Refuse renaming or removing a workflow the package ships, one set in another scope,
    one an open ticket runs, or one a project builds on."""
    _whole(resolved, name)
    if name in settings.layers(paths, None)[0].get("workflows", {}):
        raise UserError(f"workflow {name} ships with kengash; edit its steps instead")
    if f"workflows.{name}" not in settings.scope_keys(paths, project):
        where = "the defaults" if project is None else project
        raise UserError(f"workflow {name} is not set in {where}; change it where it is set")
    slugs = records.scope(paths, project)
    if project is None:
        for slug in slugs:
            own = settings.scope_keys(paths, slug)
            routed = settings.load(paths, slug).routing
            sets = f"workflows.{name}" in own
            routes = any(f"routing.{imp}" in own and routed.get(imp) == name for imp in IMPORTANCES)
            if sets or routes:
                raise UserError(f"project {slug} sets workflow {name}; change it there first")
    busy = sorted(
        doc.meta.id
        for slug in slugs
        for doc in records.project_tickets(paths, slug).values()
        if doc.meta.workflow == name and doc.meta.folder is not Folder.done
    )
    if busy:
        ids = ", ".join(busy)
        raise UserError(
            f"workflow {name} is used by open tickets: {ids}; finish or move them first"
        )
