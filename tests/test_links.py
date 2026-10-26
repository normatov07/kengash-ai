from pathlib import Path

from kengash_ai.store import links


def test_link_states(tmp_path: Path) -> None:
    repo, target, other = tmp_path / "repo", tmp_path / "store", tmp_path / "other"
    repo.mkdir()
    target.mkdir()
    assert links.link_state(repo, target) is links.LinkState.missing
    links.make_link(repo, target)
    assert links.link_state(repo, target) is links.LinkState.ok
    assert links.link_state(repo, other) is links.LinkState.wrong
    links.make_link(repo, other)
    assert links.link_state(repo, other) is links.LinkState.ok


def test_real_folder_and_file_are_obstructions(tmp_path: Path) -> None:
    (tmp_path / "a" / ".kengash").mkdir(parents=True)
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / ".kengash").write_text("x", encoding="utf-8")
    assert links.link_state(tmp_path / "a", tmp_path) is links.LinkState.real_dir
    assert links.obstruction(tmp_path / "b") is links.LinkState.blocked
    assert links.obstruction(tmp_path) is None


def test_exclude_entry_is_added_once(repo: Path) -> None:
    assert links.is_excluded(repo) is False
    assert links.ensure_excluded(repo) is True
    assert links.ensure_excluded(repo) is True
    exclude = repo / ".git" / "info" / "exclude"
    assert exclude.read_text(encoding="utf-8").splitlines().count("/.kengash") == 1
    assert links.is_excluded(repo) is True


def test_plain_folder_has_no_exclude_file(tmp_path: Path) -> None:
    assert links.ensure_excluded(tmp_path) is False
    assert links.is_excluded(tmp_path) is None


def test_equivalent_targets_count_as_ok(tmp_path: Path) -> None:
    real = tmp_path / "store"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    links.make_link(repo, alias)
    assert links.link_state(repo, real) is links.LinkState.ok
