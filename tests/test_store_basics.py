import os
from collections.abc import Callable
from datetime import date
from pathlib import Path
from uuid import UUID

import pytest

from super_harness.model import HarnessError, ProjectEntry, Registry
from super_harness.store import StorePaths, storegit
from super_harness.store.files import atomic_write
from super_harness.store.ids import new_id
from super_harness.store.locks import locked
from super_harness.store.registry import load_registry, save_registry, slugify, unique_slug


def test_atomic_write_replaces_content_without_leftovers(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "file.md"
    atomic_write(target, "one")
    atomic_write(target, "two")
    assert target.read_text(encoding="utf-8") == "two"
    assert os.listdir(target.parent) == ["file.md"]


def test_atomic_write_through_a_directory_symlink_keeps_the_link(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "link").symlink_to(real, target_is_directory=True)
    atomic_write(tmp_path / "link" / "file.md", "via link")
    assert (tmp_path / "link").is_symlink()
    assert (real / "file.md").read_text(encoding="utf-8") == "via link"


def test_new_id_rerolls_a_taken_short_id(monkeypatch: pytest.MonkeyPatch) -> None:
    taken = UUID("7b55e0c1-0000-4000-8000-000000000000")
    free = UUID("a91b3d07-0000-4000-8000-000000000000")
    monkeypatch.setattr("super_harness.store.ids.uuid4", iter([taken, free]).__next__)
    assert new_id({"7b55e0c1"}) == ("a91b3d07", free)


def test_new_id_skips_ids_that_yaml_reads_as_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    digits = UUID("12345678-0000-4000-8000-000000000000")
    exponent = UUID("1234e567-0000-4000-8000-000000000000")
    free = UUID("a91b3d07-0000-4000-8000-000000000000")
    monkeypatch.setattr("super_harness.store.ids.uuid4", iter([digits, exponent, free]).__next__)
    assert new_id(set()) == ("a91b3d07", free)


def test_lock_times_out_with_a_clear_error(tmp_path: Path) -> None:
    lock_file = tmp_path / "locks" / "x.lock"
    with (
        locked(lock_file),
        pytest.raises(HarnessError, match=r"store busy: x\.lock"),
        locked(lock_file, timeout=0.05),
    ):
        pass


@pytest.mark.parametrize(
    ("name", "slug"),
    [("Payments API", "payments-api"), ("web_dashboard", "web-dashboard"), ("--", "project")],
)
def test_slugify(name: str, slug: str) -> None:
    assert slugify(name) == slug


def test_unique_slug_appends_a_counter() -> None:
    assert unique_slug("app", {"app", "app-2"}) == "app-3"


def test_registry_round_trip(store_paths: StorePaths) -> None:
    registry = Registry(
        projects={"app": ProjectEntry(path=Path("/code/app"), added=date(2026, 10, 22))}
    )
    save_registry(store_paths, registry)
    assert load_registry(store_paths) == registry


def test_store_commits_ignore_runtime_and_skip_empty_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, run_git: Callable[..., str]
) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "absent-gitconfig"))
    home = tmp_path / "store"
    home.mkdir()
    storegit.ensure_repo(home)
    (home / "runtime").mkdir()
    (home / "runtime" / "pid").write_text("1", encoding="utf-8")
    (home / "registry.yaml").write_text("projects: {}\n", encoding="utf-8")
    assert storegit.commit(home, "harness: one") is True
    assert storegit.commit(home, "harness: none") is False
    assert run_git(home, "ls-files").split() == [".gitignore", "registry.yaml"]
