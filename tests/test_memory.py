import json
from collections.abc import Callable

import pytest

from super_harness import memory
from super_harness.model import NeedsSetup, UserError
from super_harness.store import StorePaths
from super_harness.store.seed import ensure_project, ensure_store


@pytest.fixture
def store(store_paths: StorePaths) -> StorePaths:
    ensure_store(store_paths)
    return store_paths


def memory_text(store: StorePaths) -> str:
    return (store.memory / "MEMORY.md").read_text(encoding="utf-8")


def test_lines_go_under_their_section(store: StorePaths) -> None:
    memory.add(store, "ships small, reviews hard", "said so", section="Working style")
    memory.add(store, "wants the diff, not prose", "said so", section="Working style")
    expected = (
        "## Working style\n\n- ships small, reviews hard\n- wants the diff, not prose\n\n## Goals"
    )
    assert expected in memory_text(store)


def test_decisions_are_dated_and_tagged(store: StorePaths) -> None:
    result = memory.add(
        store,
        "keyring over single secret",
        "zero-downtime rotation",
        decision=True,
        rejected="one env var",
        project="payments-api",
    )
    assert result.line.startswith("- 20")
    assert result.line.endswith(
        "[payments-api] keyring over single secret. why: zero-downtime rotation. "
        "rejected: one env var."
    )


def test_duplicates_are_not_added_twice(store: StorePaths) -> None:
    assert memory.add(store, "likes tests", "x").added is True
    assert memory.add(store, "likes tests", "x").added is False


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("two\nlines", "one line"),
        ("two\rlines", "one line"),
        ("two\u2028lines", "one line"),
        ("  ", "empty"),
        ("word " * 31, "under 30 words"),
    ],
)
def test_bad_lines_are_refused(store: StorePaths, text: str, message: str) -> None:
    with pytest.raises(UserError, match=message):
        memory.add(store, text, "x")


def test_unknown_sections_are_refused(store: StorePaths) -> None:
    with pytest.raises(UserError, match="unknown section 'Hobbies'"):
        memory.add(store, "x", "y", section="Hobbies")


def test_secrets_never_reach_memory(store: StorePaths) -> None:
    result = memory.add(store, "deploy key is sk-ant-api03-" + "a" * 24, "x")
    assert result.line == "- deploy key is [REDACTED]"
    assert "sk-ant" not in memory_text(store)


def test_writes_are_journaled_and_committed(store: StorePaths, run_git: Callable[..., str]) -> None:
    memory.add(store, "likes tests", "said so", by="claude")
    lines = [
        line for path in store.journal.glob("*.jsonl") for line in path.read_text().splitlines()
    ]
    [event] = [json.loads(line) for line in lines]
    assert (event["type"], event["file"], event["line"], event["why"], event["by"]) == (
        "memory.write",
        "MEMORY.md",
        "- likes tests",
        "said so",
        "claude",
    )
    assert "harness: memory add MEMORY.md" in run_git(store.home, "log", "--format=%s")


def test_cap_is_reported(store: StorePaths) -> None:
    path = store.memory / "MEMORY.md"
    filler = "".join(f"- fact {n}\n" for n in range(200))
    path.write_text(memory_text(store) + filler, encoding="utf-8")
    result = memory.add(store, "one more", "x")
    assert (result.over_cap, result.cap) == (True, 200)


def test_the_global_file_takes_its_cap_from_the_users_defaults(store: StorePaths) -> None:
    (store.defaults / "SETTINGS.md").write_text("memory.compact_at_lines: 50\n", encoding="utf-8")
    project = ensure_project(store, "app")
    project.settings.write_text("memory.compact_at_lines: 500\n", encoding="utf-8")
    assert memory.add(store, "likes tests", "x", project="app").cap == 50


def test_show_filters_decisions_by_project(store: StorePaths) -> None:
    memory.add(store, "alpha", "x", decision=True, project="one")
    memory.add(store, "beta", "x", decision=True, project="two")
    memory.add(store, "gamma", "x", decision=True)
    shown = memory.show(store, decisions=True, project="one")
    assert "[one] alpha." in shown
    assert "[global] gamma." in shown
    assert "[two]" not in shown


def test_memory_needs_a_store(store_paths: StorePaths) -> None:
    with pytest.raises(NeedsSetup, match="harness init"):
        memory.add(store_paths, "x", "y")
