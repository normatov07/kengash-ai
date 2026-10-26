"""The one-time move of ~/.harness to ~/.kengash (SP8 spec decision 2)."""

from pathlib import Path

import pytest

from kengash_ai.store import migrate
from kengash_ai.store.paths import kengash_home


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("KENGASH_HOME", raising=False)
    monkeypatch.delenv("HARNESS_HOME", raising=False)
    return tmp_path


def old_store(home: Path) -> Path:
    project = home / ".harness" / "projects" / "app"
    project.mkdir(parents=True)
    (project / "SETTINGS.md").write_text("loop_grant: 2\n")
    return home / ".harness"


def test_the_old_store_moves_and_leaves_a_link(home: Path) -> None:
    old = old_store(home)
    repo = home / "code" / "app"
    repo.mkdir(parents=True)
    (repo / ".harness").symlink_to(old / "projects" / "app")  # a 0.1.0 project link
    note = migrate.legacy_home()
    new = home / ".kengash"
    assert note == f"moved {old} to {new}; {old} now links to it"
    assert (new / "projects" / "app" / "SETTINGS.md").read_text() == "loop_grant: 2\n"
    assert old.is_symlink() and old.resolve() == new.resolve()
    assert (repo / ".harness" / "SETTINGS.md").read_text() == "loop_grant: 2\n"
    assert migrate.legacy_home() is None  # once only


@pytest.mark.parametrize("case", ["both real", "old is a link", "old is a file", "nothing"])
def test_nothing_moves_when_it_is_not_a_plain_old_store(home: Path, case: str) -> None:
    old, new = home / ".harness", home / ".kengash"
    if case == "both real":
        old_store(home)
        new.mkdir()
    elif case == "old is a link":
        (home / "elsewhere").mkdir()
        old.symlink_to(home / "elsewhere")
    elif case == "old is a file":
        old.write_text("x")
    before = sorted(str(p.relative_to(home)) for p in home.rglob("*"))
    assert migrate.legacy_home() is None
    assert sorted(str(p.relative_to(home)) for p in home.rglob("*")) == before


@pytest.mark.parametrize("variable", ["KENGASH_HOME", "HARNESS_HOME"])
def test_a_custom_location_is_never_moved(
    home: Path, monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    old_store(home)
    monkeypatch.setenv(variable, str(home / "custom"))
    assert migrate.legacy_home() is None
    assert (home / ".harness").is_dir() and not (home / ".harness").is_symlink()


def test_the_new_variable_wins(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert kengash_home() == home / ".kengash"
    monkeypatch.setenv("HARNESS_HOME", str(home / "old"))
    assert kengash_home() == home / "old"
    monkeypatch.setenv("KENGASH_HOME", str(home / "new"))
    assert kengash_home() == home / "new"
