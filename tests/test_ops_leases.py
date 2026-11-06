"""Loop leases: one live loop per project (SP11 spec §4)."""

import os
import subprocess
from datetime import timedelta

import pytest
from conftest import Events

from kengash_ai.model import LoopBusy, LoopLease, utc_now
from kengash_ai.ops import leases
from kengash_ai.ops.conductors import Conductor, process_name
from kengash_ai.store import StorePaths, runtime


def _me(pid: int, agent: str = "claude") -> Conductor:
    return Conductor(pid, agent, process_name(pid) or "", True)


ME = _me(os.getpid())
OTHER = _me(os.getppid(), "codex")  # alive for the whole test run


def _dead_pid() -> int:
    done = subprocess.Popen(["true"])
    done.wait()
    return done.pid


def _hold(paths: StorePaths, who: Conductor, project: str | None, *, age_s: float = 0) -> None:
    seen = utc_now() - timedelta(seconds=age_s)
    lease = LoopLease(pid=who.pid, agent=who.agent, command=who.command, project=project, seen=seen)
    runtime.save_lease(paths, lease)


def _loop_events(journal_events: Events) -> list[tuple[str, str | None, str | None]]:
    return [
        (event["type"], event.get("project"), event.get("reason"))
        for event in journal_events()
        if event["type"].startswith("loop.")
    ]


def test_overlaps() -> None:
    assert leases.overlaps(None, "a") and leases.overlaps("a", None) and leases.overlaps("a", "a")
    assert leases.overlaps(None, None)
    assert not leases.overlaps("a", "b")


def test_claim_a_free_scope_journals_started(
    store_paths: StorePaths, journal_events: Events
) -> None:
    assert leases.claim(store_paths, "app", ME) is True
    lease = runtime.load_lease(store_paths, ME.pid)
    assert lease is not None and (lease.project, lease.agent) == ("app", "claude")
    assert _loop_events(journal_events) == [("loop.started", "app", None)]


def test_claim_by_the_same_conductor_refreshes_and_rescopes(
    store_paths: StorePaths, journal_events: Events
) -> None:
    _hold(store_paths, ME, "app", age_s=600)
    before = runtime.load_lease(store_paths, ME.pid)
    assert before is not None
    assert leases.claim(store_paths, "app", ME) is False  # same scope: a refresh
    after = runtime.load_lease(store_paths, ME.pid)
    assert after is not None and after.started == before.started and after.seen > before.seen
    assert _loop_events(journal_events) == []
    assert leases.claim(store_paths, None, ME) is True  # rescoped to every project
    assert _loop_events(journal_events) == [("loop.started", None, None)]


def test_another_live_lease_on_the_same_project_is_busy(store_paths: StorePaths) -> None:
    _hold(store_paths, OTHER, "app", age_s=200)
    with pytest.raises(LoopBusy) as caught:
        leases.claim(store_paths, "app", ME)
    assert caught.value.exit_code == 6
    assert str(caught.value) == (
        f"loop running: codex pid {OTHER.pid} on app, seen 3 min ago"
        "; if that loop has ended: kengash loop claim --take-over"
    )
    assert runtime.load_lease(store_paths, ME.pid) is None


def test_a_loop_on_every_project_blocks_any_project(store_paths: StorePaths) -> None:
    _hold(store_paths, OTHER, None)
    with pytest.raises(LoopBusy, match="on all projects, seen just now"):
        leases.claim(store_paths, "app", ME)
    with pytest.raises(LoopBusy):
        leases.check(store_paths, "app", ME)


def test_claims_on_different_projects_coexist(store_paths: StorePaths) -> None:
    _hold(store_paths, OTHER, "billing")
    assert leases.claim(store_paths, "app", ME) is True
    leases.check(store_paths, "app", ME)  # no error
    assert {lease.pid for lease in leases.live(store_paths)} == {ME.pid, OTHER.pid}


def test_stale_and_dead_leases_are_claimed_and_journaled_gone(
    store_paths: StorePaths, journal_events: Events
) -> None:
    _hold(store_paths, OTHER, "app", age_s=leases.LOOP_STALE_S + 1)
    dead = _dead_pid()
    runtime.save_lease(store_paths, LoopLease(pid=dead, agent="agy", command="agy", project=None))
    assert leases.live(store_paths) == []
    assert leases.claim(store_paths, "app", ME) is True
    assert [lease.pid for lease in runtime.load_leases(store_paths)] == [ME.pid]
    found = _loop_events(journal_events)
    assert found[-1] == ("loop.started", "app", None)
    assert sorted(found[:-1], key=str) == [
        ("loop.ended", "app", "gone"),
        ("loop.ended", None, "gone"),
    ]


def test_a_reused_pid_is_not_live(store_paths: StorePaths) -> None:
    runtime.save_lease(
        store_paths,
        LoopLease(pid=OTHER.pid, agent="claude", command="not-this-program", project="app"),
    )
    assert leases.live(store_paths) == []
    assert leases.claim(store_paths, "app", ME) is True


def test_take_over_journals_taken_over(store_paths: StorePaths, journal_events: Events) -> None:
    _hold(store_paths, OTHER, None)
    assert leases.claim(store_paths, "app", ME, take_over=True) is True
    assert [lease.pid for lease in runtime.load_leases(store_paths)] == [ME.pid]
    assert _loop_events(journal_events) == [
        ("loop.ended", None, "taken_over"),
        ("loop.started", "app", None),
    ]


def test_refresh_never_recreates_a_taken_over_lease(store_paths: StorePaths) -> None:
    leases.refresh(store_paths, ME)  # no lease: nothing written
    assert runtime.load_leases(store_paths) == []
    _hold(store_paths, ME, "app", age_s=600)
    leases.refresh(store_paths, ME)
    lease = runtime.load_lease(store_paths, ME.pid)
    assert lease is not None and (utc_now() - lease.seen).total_seconds() < 5
    leases.claim(store_paths, "app", OTHER, take_over=True)
    leases.refresh(store_paths, ME)
    assert runtime.load_lease(store_paths, ME.pid) is None


def test_describe_says_just_now_then_minutes() -> None:
    now = utc_now()
    lease = LoopLease(pid=4211, agent="claude", project=None, seen=now - timedelta(seconds=59))
    assert leases.describe(lease, now) == "claude pid 4211 on all projects, seen just now"
    lease.seen = now - timedelta(seconds=150)
    assert leases.describe(lease, now) == "claude pid 4211 on all projects, seen 2 min ago"


def test_a_reused_own_pid_journals_the_old_lease_gone(
    store_paths: StorePaths, journal_events: Events
) -> None:
    runtime.save_lease(
        store_paths, LoopLease(pid=ME.pid, agent="agy", command="not-this-program", project="app")
    )
    assert leases.claim(store_paths, "app", ME) is True
    assert _loop_events(journal_events) == [
        ("loop.ended", "app", "gone"),
        ("loop.started", "app", None),
    ]


def test_a_damaged_lease_file_is_not_live_and_blocks_nothing(store_paths: StorePaths) -> None:
    _hold(store_paths, OTHER, "billing")
    store_paths.loops.mkdir(parents=True, exist_ok=True)
    (store_paths.loops / "999.json").write_text("{not json", encoding="utf-8")
    assert [lease.pid for lease in runtime.load_leases(store_paths)] == [OTHER.pid]
    assert runtime.load_lease(store_paths, 999) is None
    assert leases.claim(store_paths, "app", ME) is True
