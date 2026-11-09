"""Path claims and the limit on kengash's own test runs (SP17 spec §3.5, §3.7)."""

import threading
from pathlib import Path

from kengash_ai import scheduler
from kengash_ai.model import Settings
from kengash_ai.ops import checks, lifecycle
from kengash_ai.scheduler import PathPolicy, clash
from kengash_ai.store import StorePaths

POLICY = PathPolicy(shared=("*.g.dart",), max_overlap=2)


def test_shared_files_never_clash() -> None:
    assert not clash(["lib/a.g.dart"], ["lib/a.g.dart"], PathPolicy(("*.g.dart",), 0))


def test_a_directory_clashes_with_what_it_holds() -> None:
    assert clash(["lib/rendering/"], ["lib/rendering/x.dart"], POLICY)
    assert clash(["lib/rendering"], ["lib/rendering/x.dart"], POLICY)


def test_no_touches_means_the_whole_repo() -> None:
    assert clash([], ["a.py"], POLICY)


def test_two_shared_files_are_allowed_three_are_not() -> None:
    two = ["a.py", "b.py"]
    assert not clash(two, two, POLICY)
    three = ["a.py", "b.py", "c.py"]
    assert clash(three, three, POLICY)


def test_max_overlap_zero_is_strict() -> None:
    assert clash(["a.py"], ["a.py"], PathPolicy((), 0))


def test_disjoint_paths_do_not_clash() -> None:
    assert not clash(["a.py"], ["b.py"], PathPolicy((), 0))


def test_the_live_case_runs_side_by_side() -> None:
    settled = lifecycle.path_policy(Settings())
    one = [
        "design/spec/tokens.json",
        "lib/design/design_tokens.g.dart",
        "lib/presentation/screens/game_screen.dart",
        "lib/settings.dart",
    ]
    two = [
        "design/spec/tokens.json",
        "lib/design/design_tokens.g.dart",
        "lib/presentation/screens/game_screen.dart",
        "lib/overlay.dart",
    ]
    assert not clash(one, two, settled)


def test_select_uses_the_project_policy() -> None:
    from datetime import UTC, datetime

    from kengash_ai.model import Importance

    when = datetime(2026, 1, 1, tzinfo=UTC)
    candidate = scheduler.Candidate("b", "p", Importance.simple, when, ("a.py",), None)
    busy = [scheduler.Busy("a", "p", ("a.py",))]
    strict = scheduler.Limits(9, {})
    loose = scheduler.Limits(9, {}, PathPolicy((), 1))
    assert scheduler.select([candidate], busy, [], strict, {}, {}).chosen == []
    assert scheduler.select([candidate], busy, [], loose, {"p": loose}, {}).chosen == [candidate]


def test_checks_take_turns(tmp_path: Path) -> None:
    paths = StorePaths(tmp_path / "s")
    resolved = Settings(checks={"parallel": 1})
    entered = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with checks.turn(paths, resolved):
            entered.set()
            release.wait(10)

    thread = threading.Thread(target=holder, daemon=True)
    thread.start()
    assert entered.wait(5)
    second = threading.Event()

    def waiter() -> None:
        with checks.turn(paths, resolved):
            second.set()

    other = threading.Thread(target=waiter, daemon=True)
    other.start()
    assert not second.wait(0.6)
    release.set()
    assert second.wait(5)
    thread.join(5)
    other.join(5)
