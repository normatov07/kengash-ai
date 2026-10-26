"""Settings saves through ops: locked, journaled and committed (SP5 spec decision 7)."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from kengash_ai.ops import configure
from kengash_ai.store import StorePaths

Events = Callable[[], list[dict[str, Any]]]


def test_a_save_is_journaled_and_committed(
    registered_repo: Path,
    store_paths: StorePaths,
    journal_events: Events,
    run_git: Callable[..., str],
) -> None:
    saved = configure.save_settings({"loop_max.simple": 5}, project="payments-api", by="ui")
    assert (saved.project, saved.keys) == ("payments-api", ["loop_max.simple"])
    event = journal_events()[-1]
    assert (event["type"], event["project"], event["keys"], event["by"]) == (
        "settings.changed",
        "payments-api",
        ["loop_max.simple"],
        "ui",
    )
    log = run_git(store_paths.home, "log", "--format=%s")
    assert "kengash: settings payments-api" in log


def test_an_empty_save_journals_nothing(registered_repo: Path, journal_events: Events) -> None:
    before = len(journal_events())
    assert configure.save_settings({"loop_max.simple": 3}, project=None, by="ui").keys == []
    assert len(journal_events()) == before
