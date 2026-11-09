"""Memory lines that reach workers, and removing them (SP18 spec §3.4)."""

import pytest

from kengash_ai import memory
from kengash_ai.model import UserError
from kengash_ai.store import StorePaths
from kengash_ai.store.seed import ensure_project, ensure_store


@pytest.fixture
def store(store_paths: StorePaths) -> StorePaths:
    ensure_store(store_paths)
    ensure_project(store_paths, "app")
    return store_paths


def decisions(store: StorePaths) -> list[str]:
    text = (store.memory / "DECISIONS.md").read_text(encoding="utf-8")
    return [line for line in text.splitlines() if line.startswith("- ")]


def add(store: StorePaths, text: str, **kwargs: object) -> memory.AddResult:
    return memory.add(store, text, "reason", decision=True, project="app", **kwargs)  # type: ignore[arg-type]


def test_user_decisions_are_marked(store: StorePaths) -> None:
    add(store, "captures come first", user=True)
    assert "[app] (user) captures come first." in decisions(store)[0]


def test_user_mark_ignored_by_duplicates(store: StorePaths) -> None:
    add(store, "captures come first")
    assert not add(store, "Captures come first", user=True).added


def test_why_and_rejected_are_tightened(store: StorePaths) -> None:
    why = "first sentence stays. " + "word " * 20
    long_why = " ".join(f"w{n}" for n in range(25))
    memory.add(store, "one", why, decision=True, project="app", rejected=long_why)
    line = decisions(store)[0]
    assert "why: first sentence stays." in line and "word word" not in line
    assert "w11" in line and "w12" not in line


def test_digest_puts_user_and_touched_lines_first_in_file_order(store: StorePaths) -> None:
    add(store, "user choice", user=True)
    add(store, "about lib/board/view.dart painter")
    for number in range(60):
        add(store, f"filler decision number {number} with plenty of words to fill the cap")
    text = memory.digest(store, "app", touches=("lib/board/",))
    body = text.split("Decisions (DECISIONS.md, newest last):\n")[1].splitlines()
    assert body[0].startswith("… ")
    assert "user choice" in body[1] and "lib/board/view.dart" in body[2]
    assert "filler decision number 59" in text


def test_digest_ranks_a_line_naming_a_touched_file(store: StorePaths) -> None:
    add(store, "about lib/board/view.dart painter")
    for number in range(60):
        add(store, f"filler decision number {number} with plenty of words to fill the cap")
    text = memory.digest(store, "app", touches=("lib/board/view.dart",))
    assert "lib/board/view.dart" in text


def test_digest_drops_date_and_tag(store: StorePaths) -> None:
    add(store, "keep it short", user=True)
    text = memory.digest(store, "app")
    assert "- (user) keep it short. why: reason." in text and "[app]" not in text


def test_digest_keeps_more_than_the_old_cap(store: StorePaths) -> None:
    for number in range(14):
        add(store, f"decision {number} " + "word " * 25)
    assert "… " not in memory.digest(store, "app")


def test_forget_removes_one_line(store: StorePaths) -> None:
    add(store, "wrong decision")
    add(store, "right decision")
    removed = memory.forget(store, "WRONG decision", "app", by="test")
    assert "wrong decision" in removed
    assert len(decisions(store)) == 1


def test_forget_reaches_memory_and_process(store: StorePaths) -> None:
    memory.add(store, "prefers tabs", "said so")
    memory.add_process(store, "run the generator first", project="app", by="test")
    memory.forget(store, "prefers tabs", "app", by="test")
    memory.forget(store, "run the generator", "app", by="test")
    assert "prefers tabs" not in memory.show(store)
    assert "generator" not in store.project("app").process.read_text(encoding="utf-8")


@pytest.mark.parametrize("text", ["nothing like this", "decision"])
def test_forget_refuses_zero_or_several(store: StorePaths, text: str) -> None:
    add(store, "first decision")
    add(store, "second decision")
    with pytest.raises(UserError):
        memory.forget(store, text, "app", by="test")
    assert len(decisions(store)) == 2


def test_supersede_moves_line_to_archive_and_keeps_pinned(store: StorePaths) -> None:
    add(store, "old way")
    add(store, "fixed way (pin)")
    old, pinned = decisions(store)
    assert memory.supersede(store, old, by="test")
    assert not memory.supersede(store, pinned, by="test")
    assert decisions(store) == [pinned]
    assert "old way" in (store.memory / "archive" / "DECISIONS.md").read_text(encoding="utf-8")


def test_a_bare_top_level_claim_does_not_rank_lines(store: StorePaths) -> None:
    assert memory._rank("- 2026-01-01 [app] the library choice", ("lib/",)) == 2
    assert memory._rank("- 2026-01-01 [app] lib/board/a.dart wins", ("lib/board/",)) == 1
    assert memory._rank("- 2026-01-01 [app] see README.md first", ("README.md",)) == 1
