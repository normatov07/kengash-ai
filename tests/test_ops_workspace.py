from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import git

from kengash_ai.model import Doc, NeedsSetup, Ticket, UserError
from kengash_ai.ops import projects, workspace
from kengash_ai.store import StorePaths, documents


def test_resolve_slug_from_option_or_folder(store_paths: StorePaths, repo: Path) -> None:
    projects.init_project(repo)
    assert workspace.resolve_slug(None, repo) == "payments-api"
    assert workspace.resolve_slug("payments-api", repo.parent) == "payments-api"
    assert workspace.resolve_slug(None, repo.parent) is None
    with pytest.raises(UserError, match="unknown project: nope"):
        workspace.resolve_slug("nope", repo)


def test_project_slug_takes_a_name_or_a_folder(
    store_paths: StorePaths, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects.init_project(repo)
    (repo / "src" / "api").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(repo.parent))
    for value, cwd in [
        ("payments-api", repo.parent),
        (str(repo), repo.parent),
        ("src/api", repo),
        (".", repo / "src"),
        (f"~/{repo.name}/", Path("/")),
    ]:
        assert workspace.project_slug(value, cwd) == "payments-api", value


def test_project_slug_prefers_the_deepest_repo(store_paths: StorePaths, repo: Path) -> None:
    inner = repo / "tools"
    inner.mkdir()
    git(inner, "init", "-q", "-b", "main")
    git(inner, "commit", "-q", "--allow-empty", "-m", "init")
    projects.init_project(repo)
    projects.init_project(inner)
    (inner / "lib").mkdir()
    assert workspace.project_slug("tools/lib", repo) == "tools"
    assert workspace.project_slug(".", repo) == "payments-api"


def test_project_slug_prefers_a_slug_over_a_folder(store_paths: StorePaths, repo: Path) -> None:
    projects.init_project(repo)
    (repo.parent / "elsewhere" / "payments-api").mkdir(parents=True)
    assert workspace.project_slug("payments-api", repo.parent / "elsewhere") == "payments-api"


def test_project_slug_refuses_unknown_names_and_strangers(
    store_paths: StorePaths, repo: Path
) -> None:
    projects.init_project(repo)
    with pytest.raises(UserError, match=r"^unknown project: nope$"):
        workspace.project_slug("nope", repo)
    stranger = repo.parent / "stranger"
    stranger.mkdir()
    with pytest.raises(NeedsSetup) as caught:
        workspace.project_slug(str(stranger), repo)
    assert str(caught.value) == f"not a kengash project: {stranger}; run: kengash init {stranger}"


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
    with pytest.raises(NeedsSetup, match="kengash init"):
        workspace.context(None, repo)
