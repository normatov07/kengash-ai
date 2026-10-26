"""Content-keyed parse caches (SP7 spec decision 1): fast, never stale, never shared."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from super_harness import settings
from super_harness.model import Doc, Ticket
from super_harness.store import StorePaths, documents, memo, yamlio
from super_harness.store.seed import ensure_store

Make = Callable[..., Doc[Ticket]]


def test_memo_evicts_least_recently_used() -> None:
    made: list[str] = []
    cache: memo.Memo[str] = memo.Memo(maxsize=2)

    def make(key: str) -> Callable[[], str]:
        def build() -> str:
            made.append(key)
            return key.upper()

        return build

    assert [cache.get_or_make(k, make(k)) for k in ("a", "b", "a", "c", "a", "b")] == [
        "A",
        "B",
        "A",
        "C",
        "A",
        "B",
    ]
    assert made == ["a", "b", "c", "b"]  # "b" was least recently used when "c" came in


def test_a_ticket_rewritten_in_place_is_read_again(
    store_paths: StorePaths, make_ticket: Make
) -> None:
    project = store_paths.project("payments-api")
    path = documents.save_ticket(project, make_ticket(title="Rotate keys"))
    assert documents.load_ticket(path).meta.title == "Rotate keys"
    path.write_text(path.read_text().replace("Rotate keys", "Rotate tags"))  # same size, same inode
    assert documents.load_ticket(path).meta.title == "Rotate tags"


def test_loaded_documents_are_copies(store_paths: StorePaths, make_ticket: Make) -> None:
    path = documents.save_ticket(store_paths.project("payments-api"), make_ticket())
    first = documents.load_ticket(path)
    first.meta.title = "Changed by a caller"
    first.sections["Scope"] = "changed"
    again = documents.load_ticket(path)
    assert (again.meta.title, again.sections["Scope"]) == ("Rotate keys", "Rotate keys.")


def test_settings_are_parsed_once_per_content(
    store_paths: StorePaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    ensure_store(store_paths)
    parsed: list[str] = []
    real = yamlio.load_yaml

    def counting(text: str, source: str) -> Any:
        parsed.append(source)
        return real(text, source)

    monkeypatch.setattr(settings, "load_yaml", counting)
    first = settings.load(store_paths)
    settings.load(store_paths)
    assert parsed.count("defaults/SETTINGS.md") <= 1  # the second load parses nothing
    first.loop_max.simple = 99
    assert settings.load(store_paths).loop_max.simple == 3  # callers get their own copy
    defaults: Path = store_paths.defaults / "SETTINGS.md"
    text = defaults.read_text()
    assert "loop_grant: 2" in text
    defaults.write_text(text.replace("loop_grant: 2", "loop_grant: 5"))  # in place, same size
    assert settings.load(store_paths).loop_grant == 5
