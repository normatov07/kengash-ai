"""Memory compaction: the compact job (SP3 spec decision 31)."""

from pathlib import Path

from conftest import COMPACTED, PINNED, Events, FakeClis

from super_harness.ops import compaction
from super_harness.store import StorePaths, runtime


def test_run_compaction_accepts_a_shorter_file_that_keeps_pins(
    long_memory: Path, store_paths: StorePaths, fake_clis: FakeClis
) -> None:
    fake_clis.queue("claude", stdout=fake_clis.claude_output({"text": COMPACTED}))
    assert compaction.run_compaction() == "MEMORY.md 19 → 16 lines"
    assert long_memory.read_text(encoding="utf-8") == COMPACTED
    (call,) = fake_clis.calls("claude")
    argv = call["argv"]
    assert call["cwd"] == str(store_paths.memory)
    assert argv[argv.index("--model") + 1] == "haiku" and "dontAsk" in argv
    prompt = argv[argv.index("-p") + 1]
    assert "at most 13 lines" in prompt and PINNED in prompt
    assert runtime.load_slots(store_paths).held == []


def test_run_compaction_rejects_a_result_without_pins(
    long_memory: Path, fake_clis: FakeClis
) -> None:
    before = long_memory.read_text(encoding="utf-8")
    unpinned = COMPACTED.replace(f"{PINNED}\n", "")
    fake_clis.queue("claude", stdout=fake_clis.claude_output({"text": unpinned}))
    assert compaction.run_compaction() == (
        f"MEMORY.md kept (19 lines): the result drops 1 pinned line(s): {PINNED}"
    )
    assert long_memory.read_text(encoding="utf-8") == before


def test_a_failed_compaction_call_journals_worker_exited(
    long_memory: Path, fake_clis: FakeClis, journal_events: Events
) -> None:
    fake_clis.queue("claude", fixture="claude/auth_error.json")
    compaction.run_compaction()
    event = journal_events()[-1]
    assert (event["type"], event["job"], event["ok"], event["reason"]) == (
        "worker.exited",
        "compact",
        False,
        "sign in to claude interactively",
    )
