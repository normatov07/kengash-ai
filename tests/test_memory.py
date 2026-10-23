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


CURRENT = [
    "# MEMORY.md",
    "",
    "## Working style",
    "",
    "- ships small (pin)",
    "- ships small",
    "- ships small changes",
    "",
    "## Goals",
    "",
    "- payments first",
]
GOOD = [
    "# MEMORY.md",
    "",
    "## Working style",
    "",
    "- ships small (pin)",
    "",
    "## Goals",
    "",
    "- payments first",
]


def test_compaction_problem_names_each_rejection() -> None:
    assert memory.compaction_problem(CURRENT, GOOD, cap=20) is None
    assert memory.compaction_problem(CURRENT, ["", "  "], cap=20) == "the result is empty"
    unpinned = [line for line in GOOD if "(pin)" not in line]
    assert memory.compaction_problem(CURRENT, unpinned, cap=20) == (
        "the result drops 1 pinned line(s): - ships small (pin)"
    )
    headless = [line for line in GOOD if line != "## Goals"]
    assert memory.compaction_problem(CURRENT, headless, cap=20) == (
        "the result drops the heading ## Goals"
    )
    assert memory.compaction_problem(CURRENT, GOOD, cap=9) == "the result has 9 lines; the cap is 9"


def test_merge_added_keeps_lines_written_meanwhile() -> None:
    current = [*CURRENT[:7], "- reviews hard", *CURRENT[7:], "- new goal"]
    assert memory.merge_added(CURRENT, current, GOOD) == [
        "# MEMORY.md",
        "",
        "## Working style",
        "",
        "- ships small (pin)",
        "- reviews hard",
        "",
        "## Goals",
        "",
        "- payments first",
        "- new goal",
    ]
    assert memory.merge_added(CURRENT, current, current) == current


def test_apply_compaction_replaces_memory_and_journals(
    store: StorePaths, run_git: Callable[..., str]
) -> None:
    memory.add(store, "ships small (pin)", "said so", section="Working style")
    memory.add(store, "ships small", "said so", section="Working style")
    snapshot = memory_text(store)
    compacted = snapshot.replace("- ships small\n", "")
    outcome = memory.apply_compaction(
        store, snapshot, compacted, cap=50, detail={"provider": "claude"}
    )
    lines = len(snapshot.splitlines())
    assert outcome == memory.Compaction(before=lines, after=lines - 1, accepted=True)
    assert memory_text(store) == compacted
    event = json.loads(next(store.journal.glob("*.jsonl")).read_text().splitlines()[-1])
    assert (event["type"], event["accepted"], event["provider"], event["by"]) == (
        "memory.compacted",
        True,
        "claude",
        "harness",
    )
    assert run_git(store.home, "log", "-1", "--format=%s").strip() == "harness: memory compact"


def test_a_rejected_compaction_leaves_memory_alone(store: StorePaths) -> None:
    memory.add(store, "ships small (pin)", "said so", section="Working style")
    snapshot = memory_text(store)
    outcome = memory.apply_compaction(
        store, snapshot, snapshot.replace("- ships small (pin)\n", ""), cap=50, detail={}
    )
    assert not outcome.accepted and "pinned" in outcome.reason
    assert memory_text(store) == snapshot
    event = json.loads(next(store.journal.glob("*.jsonl")).read_text().splitlines()[-1])
    assert (event["type"], event["accepted"]) == ("memory.compacted", False)


def test_only_entries_marked_pin_are_pinned() -> None:
    intro = "Lines marked (pin) survive compaction."
    assert memory.compaction_problem([intro, *CURRENT], GOOD, cap=20) is None


def test_decisions_past_300_lines_move_their_oldest_to_the_archive(store: StorePaths) -> None:
    path = store.memory / "DECISIONS.md"
    header = path.read_text(encoding="utf-8").splitlines()
    old = [f"- 2026-01-01 [global] decision {n:03d}. why: test." for n in range(300 - len(header))]
    path.write_text("\n".join([*header, *old]) + "\n", encoding="utf-8")
    first = memory.add(store, "keyring", "rotation", decision=True)
    memory.add(store, "short ids", "readable", decision=True)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert (first.lines, len(lines), first.over_cap) == (300, 300, False)
    assert lines[: len(header)] == header and lines[len(header)] == old[2]
    archive = (store.memory / "archive" / "DECISIONS.md").read_text(encoding="utf-8")
    assert archive == memory.ARCHIVE_HEADER + f"{old[0]}\n{old[1]}\n"
    events = [
        json.loads(line) for line in next(store.journal.glob("*.jsonl")).read_text().splitlines()
    ]
    assert events[-1]["archived"] == 1
