from collections.abc import Callable
from pathlib import Path

import pytest

from super_harness.model import Doc, NeedsSetup, Ticket, UserError
from super_harness.ops import projects, workspace
from super_harness.store import StorePaths, documents


def test_resolve_slug_from_option_or_folder(store_paths: StorePaths, repo: Path) -> None:
    projects.init_project(repo)
    assert workspace.resolve_slug(None, repo) == "payments-api"
    assert workspace.resolve_slug("payments-api", repo.parent) == "payments-api"
    assert workspace.resolve_slug(None, repo.parent) is None
    with pytest.raises(UserError, match="unknown project: nope"):
        workspace.resolve_slug("nope", repo)


def test_settings_follow_the_current_project(store_paths: StorePaths, repo: Path) -> None:
    projects.init_project(repo)
    store_paths.project("payments-api").settings.write_text(
        "loop_max.critical: 9\n", encoding="utf-8"
    )
    assert workspace.setting("loop_max.critical", None, repo) == 9
    assert workspace.setting("loop_max.critical", None, repo.parent) == 6


def test_context_shows_memory_process_and_gates(
    store_paths: StorePaths, repo: Path, make_ticket: Callable[..., Doc[Ticket]]
) -> None:
    projects.init_project(repo)
    project = store_paths.project("payments-api")
    documents.save_ticket(project, make_ticket(status="in_process/needs_approval"))
    documents.save_ticket(project, make_ticket("a91b3d07", status="in_process/under_review"))
    digest = workspace.context(None, repo)
    assert digest.memory.startswith("# MEMORY.md")
    assert (digest.project, digest.process) == (
        "payments-api",
        ["# PROCESS.md", "## Process notes"],
    )
    assert digest.gates == [workspace.OpenGate("7b55e0c1", "needs_approval", "Rotate keys")]


def test_context_outside_a_project_has_memory_only(store_paths: StorePaths, repo: Path) -> None:
    projects.init_project(repo)
    digest = workspace.context(None, repo.parent)
    assert (digest.project, digest.process, digest.gates) == (None, [], [])


def test_context_needs_a_store(store_paths: StorePaths, repo: Path) -> None:
    with pytest.raises(NeedsSetup, match="harness init"):
        workspace.context(None, repo)
