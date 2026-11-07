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


def _worktree(repo: Path, name: str) -> Path:
    """A linked worktree of `repo` elsewhere, as Orca makes one per workspace."""
    folder = repo.parent / "orca" / "workspaces" / name
    folder.parent.mkdir(parents=True, exist_ok=True)
    git(repo, "worktree", "add", "-q", "-b", f"normatov13/{name}", str(folder))
    return Path(git(folder, "rev-parse", "--show-toplevel").strip())


def test_main_repo_of_a_checkout_a_worktree_and_a_stranger(repo: Path) -> None:
    from kengash_ai.ops import records

    worktree = _worktree(repo, "sculpin")
    assert records.main_repo(repo) == repo
    assert records.main_repo(worktree / "lib" if (worktree / "lib").is_dir() else worktree) == repo
    stranger = repo.parent / "stranger"
    stranger.mkdir()
    assert records.main_repo(stranger) is None


def test_a_broken_worktree_has_no_main_repo(repo: Path) -> None:
    from kengash_ai.ops import records

    worktree = _worktree(repo, "saithe")
    git(repo, "worktree", "remove", "--force", str(worktree))
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text(f"gitdir: {repo}/.git/worktrees/gone\n", encoding="utf-8")
    assert records.main_repo(worktree) is None


def test_a_worktree_resolves_to_its_repos_project(store_paths: StorePaths, repo: Path) -> None:
    projects.init_project(repo)
    worktree = _worktree(repo, "sculpin")
    (worktree / "lib").mkdir()
    assert workspace.resolve_slug(None, worktree / "lib") == "payments-api"
    assert workspace.project_slug(str(worktree), repo.parent) == "payments-api"
    assert workspace.project_slug(".", worktree / "lib") == "payments-api"


def test_init_in_a_worktree_registers_nothing(store_paths: StorePaths, repo: Path) -> None:
    from kengash_ai.store.registry import load_registry

    projects.init_project(repo)
    worktree = _worktree(repo, "main-ws")
    found = projects.init_project(worktree)
    assert (found.slug, found.created) == ("payments-api", False)
    assert found.warnings == [
        f"{worktree} is a worktree of payments-api; kengash uses payments-api here"
    ]
    assert list(load_registry(store_paths).projects) == ["payments-api"]
    assert not (worktree / ".kengash").exists()
