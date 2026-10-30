"""Workflows through ops: create, copy, rename, remove, route and set (SP10 spec §4.5-4.6)."""

import re
from collections.abc import Callable
from pathlib import Path

import pytest

from kengash_ai import settings
from kengash_ai.model import Doc, Ticket, UserError
from kengash_ai.ops import workflows
from kengash_ai.store import StorePaths, documents

MakeTicket = Callable[..., Doc[Ticket]]


def scope_files(paths: StorePaths) -> dict[str, bytes]:
    files = {
        "defaults": paths.defaults / "SETTINGS.md",
        "project": paths.project("payments-api").settings,
    }
    return {name: path.read_bytes() for name, path in files.items() if path.is_file()}


def test_new_blank_and_copied(registered_repo: Path, store_paths: StorePaths) -> None:
    blank = workflows.new_workflow("hotfix", project=None, by="cli")
    assert (blank.name, blank.keys) == ("hotfix", ["workflows.hotfix"])
    resolved = settings.load(store_paths)
    assert (resolved.workflows["hotfix"].steps, resolved.workflows["hotfix"].on_fail) == (
        ["implement"],
        {},
    )
    workflows.new_workflow("careful", from_="critical", project=None, by="cli")
    assert settings.load(store_paths).workflows["careful"] == resolved.workflows["critical"]
    with pytest.raises(UserError, match=r"^workflow hotfix exists$"):
        workflows.new_workflow("hotfix", project=None, by="cli")
    with pytest.raises(UserError, match=r"^unknown workflow nope; known: simple, "):
        workflows.new_workflow("other", from_="nope", project=None, by="cli")


def test_names_are_checked(registered_repo: Path, store_paths: StorePaths) -> None:
    before = scope_files(store_paths)
    with pytest.raises(
        UserError, match=re.escape("workflow name must match [a-z][a-z0-9_-]{0,30}")
    ):
        workflows.new_workflow("Hot Fix", project=None, by="cli")
    assert scope_files(store_paths) == before


def test_rename_moves_routing(registered_repo: Path, store_paths: StorePaths) -> None:
    workflows.new_workflow("hotfix", project=None, by="cli")
    workflows.route("critical", "hotfix", project=None, by="cli")
    change = workflows.rename_workflow("hotfix", "quickfix", project=None, by="cli")
    assert set(change.keys) == {"workflows.hotfix", "workflows.quickfix", "routing.critical"}
    resolved = settings.load(store_paths)
    assert "hotfix" not in resolved.workflows and resolved.workflow_for("critical") == "quickfix"


def test_shipped_workflows_keep_their_names(registered_repo: Path, store_paths: StorePaths) -> None:
    message = "workflow critical ships with kengash; edit its steps instead"
    with pytest.raises(UserError, match=f"^{re.escape(message)}$"):
        workflows.rename_workflow("critical", "careful", project=None, by="cli")
    with pytest.raises(UserError, match=f"^{re.escape(message)}$"):
        workflows.remove_workflow("critical", project=None, by="cli")


def test_in_use_by_tickets_is_kept(
    registered_repo: Path, store_paths: StorePaths, make_ticket: MakeTicket
) -> None:
    workflows.new_workflow("hotfix", project=None, by="cli")
    project = store_paths.project("payments-api")
    documents.save_ticket(project, make_ticket("aa11bb22", workflow="hotfix"))
    documents.save_ticket(project, make_ticket("cc33dd44", workflow="hotfix", status="done/merged"))
    message = "workflow hotfix is used by open tickets: aa11bb22; finish or move them first"
    with pytest.raises(UserError, match=f"^{re.escape(message)}$"):
        workflows.remove_workflow("hotfix", project=None, by="cli")
    with pytest.raises(UserError, match=f"^{re.escape(message)}$"):
        workflows.rename_workflow("hotfix", "quickfix", project=None, by="cli")


def test_routed_workflow_is_kept(registered_repo: Path, store_paths: StorePaths) -> None:
    workflows.new_workflow("hotfix", project=None, by="cli")
    workflows.route("standard", "hotfix", project=None, by="cli")
    message = "workflow hotfix is routed from standard; route it elsewhere first"
    with pytest.raises(UserError, match=f"^{re.escape(message)}$"):
        workflows.remove_workflow("hotfix", project=None, by="cli")
    workflows.route("standard", "standard", project=None, by="cli")
    removed = workflows.remove_workflow("hotfix", project=None, by="cli")
    assert removed.keys == ["workflows.hotfix"]
    assert "hotfix" not in settings.load(store_paths).workflows


def test_defaults_workflow_used_by_a_project_is_kept(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    workflows.new_workflow("hotfix", project=None, by="cli")
    workflows.route("critical", "hotfix", project="payments-api", by="cli")
    before = scope_files(store_paths)
    message = "project payments-api sets workflow hotfix; change it there first"
    with pytest.raises(UserError, match=f"^{re.escape(message)}$"):
        workflows.remove_workflow("hotfix", project=None, by="cli")
    with pytest.raises(UserError, match=f"^{re.escape(message)}$"):
        workflows.rename_workflow("hotfix", "quickfix", project=None, by="cli")
    assert scope_files(store_paths) == before


def test_change_a_workflow_where_it_is_set(registered_repo: Path, store_paths: StorePaths) -> None:
    workflows.new_workflow("hotfix", project=None, by="cli")
    message = "workflow hotfix is not set in payments-api; change it where it is set"
    with pytest.raises(UserError, match=f"^{re.escape(message)}$"):
        workflows.remove_workflow("hotfix", project="payments-api", by="cli")


def test_route_and_set_validate(registered_repo: Path, store_paths: StorePaths) -> None:
    with pytest.raises(
        UserError, match=r"^unknown importance urgent; known: simple, standard, critical$"
    ):
        workflows.route("urgent", "simple", project=None, by="cli")
    before = scope_files(store_paths)
    with pytest.raises(UserError, match="on_fail edges must join steps"):
        workflows.set_workflow(
            "simple", ["plan", "implement"], {"review_code": "implement"}, project=None, by="cli"
        )
    assert scope_files(store_paths) == before
    change = workflows.set_workflow(
        "simple",
        ["plan", "implement", "review_code"],
        {"review_code": "plan"},
        project=None,
        by="cli",
    )
    assert change.keys == ["workflows.simple"]
    assert settings.load(store_paths).workflows["simple"].on_fail == {"review_code": "plan"}
