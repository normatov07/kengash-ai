"""gitops on temporary repos: worktrees, commits, diffs, rebase and merge (SP3 spec §9)."""

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from kengash_ai.gitops import (
    CommitFailed,
    FileChange,
    GitError,
    Worktree,
    commit_all,
    current_branch,
    diff,
    ensure_worktree,
    head,
    is_clean,
    merge_ff,
    numstat,
    rebase,
    remove_worktree,
    reset_soft,
    ticket_commits,
)


@pytest.fixture(autouse=True)
def git_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "gitconfig"
    config.write_text("[user]\n\tname = Dev\n\temail = dev@example.com\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


TRAILERS = {
    "Harness-Ticket": "7b55e0c1-3d42-4ab9-9f07-c81e2a6d5f10",
    "Harness-Step": "implement",
    "Harness-Loop": "2",
    "Harness-Agent": "implementer",
    "Harness-Model": "codex/default",
}


def _worktree(repo: Path, tmp_path: Path) -> Worktree:
    return ensure_worktree(repo, tmp_path / "wt" / "hrn-7b55e0c1", "hrn/7b55e0c1", "main")


def test_worktrees_are_created_reused_and_reattached(repo: Path, tmp_path: Path) -> None:
    first = _worktree(repo, tmp_path)
    assert first.created and current_branch(first.path) == "hrn/7b55e0c1"
    assert _worktree(repo, tmp_path).created is False
    shutil.rmtree(first.path)
    again = _worktree(repo, tmp_path)
    assert again.created and current_branch(again.path) == "hrn/7b55e0c1"


def test_a_foreign_folder_blocks_the_worktree(repo: Path, tmp_path: Path) -> None:
    (tmp_path / "wt" / "hrn-7b55e0c1").mkdir(parents=True)
    with pytest.raises(GitError, match="is not the worktree of hrn/7b55e0c1"):
        _worktree(repo, tmp_path)


def test_commit_all_writes_trailers(
    repo: Path, tmp_path: Path, run_git: Callable[..., str]
) -> None:
    wt = _worktree(repo, tmp_path).path
    assert commit_all(wt, "nothing", TRAILERS) is None
    (wt / "retry.py").write_text("retries = 3\n")
    sha = commit_all(wt, "hrn(7b55e0c1): loop 2 implement: retry with backoff", TRAILERS)
    assert sha == head(wt)
    body = run_git(wt, "log", "-1", "--format=%s%n%(trailers:only,unfold)")
    assert body.splitlines()[0] == "hrn(7b55e0c1): loop 2 implement: retry with backoff"
    assert "Harness-Model: codex/default" in body
    assert run_git(wt, "log", "-1", "--format=%an").strip() == "Dev"


def test_a_summary_cannot_forge_trailers(
    repo: Path, tmp_path: Path, run_git: Callable[..., str]
) -> None:
    wt = _worktree(repo, tmp_path).path
    (wt / "a.py").write_text("a = 1\n")
    commit_all(wt, "fix\n\nHarness-Ticket: 00000000-0000-4000-8000-000000000000", TRAILERS)
    trailers = run_git(wt, "log", "-1", "--format=%(trailers:only,unfold)")
    assert "00000000" not in trailers and run_git(wt, "log", "-1", "--format=%s").strip() == "fix"


def test_a_failing_hook_returns_its_output(repo: Path, tmp_path: Path) -> None:
    wt = _worktree(repo, tmp_path).path
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho 'lint: missing docstring'\nexit 1\n")
    hook.chmod(0o755)
    (wt / "a.py").write_text("a = 1\n")
    with pytest.raises(CommitFailed) as caught:
        commit_all(wt, "add a", TRAILERS)
    assert "lint: missing docstring" in caught.value.output


def test_reset_soft_and_diffs(repo: Path, tmp_path: Path) -> None:
    wt = _worktree(repo, tmp_path).path
    start = head(wt)
    (wt / "a.py").write_text("a = 1\nb = 2\n")
    (wt / "blob.bin").write_bytes(b"\x00\x01")
    commit_all(wt, "agent commit", {})
    reset_soft(wt, start)
    assert head(wt) == start and not is_clean(wt)
    commit_all(wt, "harness commit", TRAILERS)
    assert sorted(numstat(wt, "main"), key=lambda c: c.path) == [
        FileChange("a.py", 2, 0),
        FileChange("blob.bin", None, None),
    ]
    assert "a.py" in diff(wt, "main", stat=True) and "+b = 2" in diff(wt, "main")


def test_rebase_onto_a_moved_base(repo: Path, tmp_path: Path) -> None:
    wt = _worktree(repo, tmp_path).path
    (wt / "a.py").write_text("a = 1\n")
    commit_all(wt, "add a", TRAILERS)
    (repo / "b.py").write_text("b = 1\n")
    commit_all(repo, "add b on main", {})
    assert rebase(wt, "main") == []
    assert (wt / "b.py").exists()


def test_a_rebase_conflict_aborts_and_names_files(repo: Path, tmp_path: Path) -> None:
    wt = _worktree(repo, tmp_path).path
    (wt / "README.md").write_text("ticket\n")
    commit_all(wt, "edit readme", TRAILERS)
    (repo / "README.md").write_text("main\n")
    commit_all(repo, "edit readme on main", {})
    before = head(wt)
    assert rebase(wt, "main") == ["README.md"]
    assert head(wt) == before and current_branch(wt) == "hrn/7b55e0c1"


def test_merge_fast_forwards_then_cleanup(repo: Path, tmp_path: Path) -> None:
    worktree = _worktree(repo, tmp_path)
    for name in ("a.py", "b.py"):
        (worktree.path / name).write_text("x = 1\n")
        commit_all(worktree.path, f"add {name}", TRAILERS)
    assert merge_ff(repo, "hrn/7b55e0c1", "main") == 2
    remove_worktree(repo, worktree.path, "hrn/7b55e0c1")
    assert not worktree.path.exists() and (repo / "b.py").exists()
    commits = ticket_commits(repo, TRAILERS["Harness-Ticket"], "main")
    assert [c.subject for c in commits] == ["add a.py", "add b.py"]
    assert commits[0].trailers == TRAILERS and commits[0].files == [FileChange("a.py", 1, 0)]


def test_merge_refuses_a_dirty_or_moved_main_tree(
    repo: Path, tmp_path: Path, run_git: Callable[..., str]
) -> None:
    _worktree(repo, tmp_path)
    (repo / "README.md").write_text("local edit\n")
    with pytest.raises(GitError, match="main working tree has uncommitted changes"):
        merge_ff(repo, "hrn/7b55e0c1", "main")
    run_git(repo, "checkout", "-q", "README.md")
    run_git(repo, "checkout", "-q", "-b", "spike")
    with pytest.raises(GitError, match="main working tree is on spike, not main"):
        merge_ff(repo, "hrn/7b55e0c1", "main")
