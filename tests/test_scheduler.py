from datetime import UTC, datetime, timedelta

from kengash_ai.model import Importance
from kengash_ai.scheduler import Busy, Candidate, Held, Limits, fits, overlaps, select

T0 = datetime(2026, 10, 22, 9, 0, tzinfo=UTC)
ROOMY = Limits(total=8, per_provider={"claude": 8, "codex": 8})


def candidate(
    ticket_id: str,
    project: str = "app",
    importance: Importance = Importance.standard,
    *,
    age: int = 0,
    touches: tuple[str, ...] = ("src",),
    provider: str | None = "claude",
) -> Candidate:
    created = T0 - timedelta(minutes=age)
    return Candidate(ticket_id, project, importance, created, touches, provider)


def test_paths_overlap_by_whole_segments() -> None:
    assert not overlaps(["services/web"], ["services/webhooks"])
    assert overlaps(["services"], ["services/web/app.py"])
    assert overlaps(["./a/b/"], ["a/b/c"])
    assert overlaps([], ["docs"])
    assert overlaps(["."], ["docs"])
    assert not overlaps(["a", "b"], ["c"])


def test_running_and_chosen_tickets_keep_their_paths() -> None:
    picks = select(
        [
            candidate("t1", touches=("src/api",)),
            candidate("t2", touches=("src/api/v2",)),
            candidate("t3", touches=("docs",)),
            candidate("t4", "web", touches=("src",)),
        ],
        busy=[Busy("r1", "app", ("docs",))],
        held=[],
        machine=ROOMY,
        projects={},
        last_claims={},
    )
    assert [c.id for c in picks.chosen] == ["t1", "t4"]
    assert picks.held_back == {"t2": "touches overlap t1", "t3": "touches overlap r1"}


def test_slots_are_counted_per_machine_and_per_project() -> None:
    machine = Limits(total=8, per_provider={"claude": 2, "codex": 3})
    web = Limits(total=1, per_provider={"codex": 3})
    picks = select(
        [
            candidate("a1", touches=("a",)),
            candidate("a2", touches=("b",)),
            candidate("w1", "web", touches=("a",), provider="codex"),
            candidate("w2", "web", touches=("b",), provider="codex"),
            candidate("w3", "web", touches=("c",), provider=None),
        ],
        busy=[],
        held=[Held("other", "claude")],
        machine=machine,
        projects={"web": web},
        last_claims={},
    )
    assert [c.id for c in picks.chosen] == ["a1", "w1", "w3"]
    assert picks.held_back == {"a2": "no free claude slot", "w2": "no free codex slot"}


def test_projects_take_turns_and_critical_tickets_go_first() -> None:
    picks = select(
        [
            candidate("a1", touches=("x",), age=5),
            candidate("a2", importance=Importance.critical, touches=("y",)),
            candidate("a3", touches=("z",), age=9),
            candidate("w1", "web", Importance.simple, touches=("x",)),
        ],
        busy=[],
        held=[],
        machine=ROOMY,
        projects={},
        last_claims={"app": T0},
    )
    assert [c.id for c in picks.chosen] == ["w1", "a2", "a3", "a1"]


def test_fits_checks_machine_and_project_limits() -> None:
    machine = Limits(3, {"claude": 2})
    projects = {"a": Limits(1, {"claude": 1})}
    assert fits("claude", "b", [Held("a", "claude")], machine, projects)
    assert not fits("claude", "a", [Held("a", "claude")], machine, projects)
    assert not fits("claude", "b", [Held("a", "claude"), Held("b", "claude")], machine, projects)
    assert not fits("codex", "b", [], machine, projects)
