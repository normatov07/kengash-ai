"""Read models for the UI screens (SP5 spec §3)."""

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from super_harness import journal
from super_harness.model import (
    ConductorPing,
    Doc,
    Event,
    ProviderStatus,
    SlotEntry,
    SlotTable,
    Ticket,
    utc_now,
)
from super_harness.ops import agents, configure, views
from super_harness.store import StorePaths, documents, runtime

Make = Callable[..., Doc[Ticket]]


def step_end(ticket: str, provider: str, tokens: int, *, added: int = 0, ago: int = 0) -> Event:
    return Event.model_validate(
        {
            "ts": utc_now() - timedelta(days=ago),
            "type": "step.end",
            "project": "payments-api",
            "ticket": ticket,
            "step": "implement",
            "provider": provider,
            "tokens": {"in": tokens, "out": 0},
            "added": added,
            "removed": 1,
        }
    )


@pytest.fixture
def seeded(registered_repo: Path, store_paths: StorePaths, make_ticket: Make) -> StorePaths:
    project = store_paths.project("payments-api")
    for doc in (
        make_ticket("aaaaaaa1", status="in_queue/ready", touches=["a"], title="<script>x</script>"),
        make_ticket("aaaaaaa2", status="in_queue/blocked", touches=[]),
        make_ticket("aaaaaaa3", status="in_process/under_implementation", step="implement"),
        make_ticket("aaaaaaa4", status="in_process/needs_approval", step="security", loop=6),
        make_ticket("aaaaaaa5", status="done/merged"),
    ):
        documents.save_ticket(project, doc)
    for event in (
        step_end("aaaaaaa3", "codex", 1000, added=128),
        step_end("aaaaaaa3", "claude", 500, added=2, ago=3),
        Event.model_validate(
            {
                "type": "ticket.needs_approval",
                "project": "payments-api",
                "ticket": "aaaaaaa4",
                "status": "in_process/needs_approval",
                "reason": "loop cap 6/6",
            }
        ),
        Event(type="ticket.merged", project="payments-api", ticket="aaaaaaa5"),
    ):
        journal.append(store_paths, event)
    held = SlotEntry(
        provider="codex", project="payments-api", ticket="aaaaaaa3", step="implement", pid=1
    )
    runtime.save_slots(store_paths, SlotTable(held=[held]))
    runtime.save_ping(store_paths, ConductorPing(pid=4242, agent="claude", project=None))
    return store_paths


def test_an_empty_store_has_an_empty_overview(store_paths: StorePaths) -> None:
    empty = views.overview(store_paths, window="today")
    assert (empty.projects, empty.sessions, empty.gates, empty.tail) == ([], [], [], [])
    assert all(not column.cards for column in views.board(store_paths, project=None).columns)


def test_the_overview_counts_sessions_queue_gates_and_spend(seeded: StorePaths) -> None:
    found = views.overview(seeded, window="today")
    assert found.projects == ["payments-api"]
    assert [(s.ticket, s.step) for s in found.sessions] == [("aaaaaaa3", "implement")]
    assert (found.queue.ready, found.queue.blocked, found.queue.parallel, found.queue.serial) == (
        1,
        1,
        1,
        1,
    )
    (gate,) = found.gates
    assert (gate.ticket, gate.reason, gate.loop) == ("aaaaaaa4", "loop cap 6/6", 6)
    assert found.done_today == 1
    assert found.spend == {"codex": 1000}
    assert views.overview(seeded, window="7d").spend == {"codex": 1000, "claude": 500}
    codex = next(slot for slot in found.slots if slot.provider == "codex")
    assert (codex.used, codex.total) == (1, 3)
    assert [c.agent for c in found.conductors] == ["claude"]
    assert found.tail[-1]["type"] == "ticket.merged"


def test_the_board_puts_cards_in_their_columns(seeded: StorePaths) -> None:
    columns = {c.key: c for c in views.board(seeded, project=None).columns}
    assert [card.id for card in columns["in_queue"].cards] == ["aaaaaaa1", "aaaaaaa2"]
    assert [card.id for card in columns["implement"].cards] == ["aaaaaaa3"]
    assert [card.id for card in columns["needs_you"].cards] == ["aaaaaaa4"]
    assert [card.id for card in columns["done"].cards] == ["aaaaaaa5"]
    card: Any = columns["implement"].cards[0]
    assert (card.added, card.removed, card.provider) == (130, 2, "codex")
    assert columns["in_queue"].cards[0].title == "<script>x</script>"  # escaped by the UI


def test_links_report_each_projects_link_and_its_fix(
    registered_repo: Path, store_paths: StorePaths, tmp_path: Path, run_git: Callable[..., str]
) -> None:
    healthy = views.links(store_paths)
    (project,) = healthy.projects
    assert (project.state, project.memory, project.excluded, project.fix) == ("ok", "ok", True, "")
    assert (healthy.intact, healthy.total) == (1, 1)
    assert project.link == str(registered_repo / ".harness")
    (registered_repo / ".harness").unlink()
    broken = views.links(store_paths).projects[0]
    assert (broken.state, broken.fix, broken.hint) == ("missing", "repair", "harness doctor --fix")
    (registered_repo / ".harness").mkdir()
    real = views.links(store_paths).projects[0]
    assert (real.state, real.fix) == ("real folder", "adopt")
    assert real.hint == f"harness adopt {registered_repo}"


def test_a_moved_repo_needs_a_relink(registered_repo: Path, store_paths: StorePaths) -> None:
    registered_repo.rename(registered_repo.with_name("moved"))
    moved = views.links(store_paths).projects[0]
    assert (moved.state, moved.fix) == ("repo missing", "relink")
    assert moved.hint == "harness link payments-api <new-path>"
    assert views.overview(store_paths, window="today").links_broken == 1


def test_stores_found_beside_registered_repos_are_listed(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    other = registered_repo.parent / "legacy-crm" / ".harness"
    (other / "tasks" / "in_queue").mkdir(parents=True)
    (other / "tasks" / "in_queue" / "aaaaaaa1.md").write_text("---\n---\n")
    (other / "plans").mkdir()
    (found,) = views.links(store_paths).nearby
    assert (found.path, found.repo, found.tickets, found.plans) == (
        str(other),
        str(other.parent),
        1,
        0,
    )


def test_past_journal_days_are_parsed_once(
    seeded: StorePaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    parsed: list[str] = []
    read_day = journal.read_day

    def counting(path: Path) -> list[Event]:
        parsed.append(path.stem)
        return read_day(path)

    monkeypatch.setattr(journal, "read_day", counting)
    views.overview(seeded)
    journal.append(seeded, Event(type="ticket.moved", project="payments-api", ticket="aaaaaaa2"))
    tail = views.overview(seeded).tail
    past = (utc_now() - timedelta(days=3)).date().isoformat()
    assert parsed.count(past) == 1
    assert tail[-1]["type"] == "ticket.moved" and tail[-1]["ticket"] == "aaaaaaa2"


def test_settings_mark_only_the_projects_overrides(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    configure.save_settings({"loop_max.critical": 8}, project="payments-api", by="ui")
    found = views.settings_view(store_paths, project="payments-api")
    assert found.set_here == ["loop_max.critical"]
    assert found.values["loop_max"]["critical"] == 8 and found.problem == ""
    assert found.repo_path == str(registered_repo / ".harness" / "SETTINGS.md")
    assert "loop_max.critical: 8" in found.file
    defaults = views.settings_view(store_paths, project=None)
    assert defaults.set_here == [] and defaults.repo_path is None


def test_a_broken_settings_file_is_shown_with_its_problem(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    store_paths.project("payments-api").settings.write_text("loop_maxx.simple: 3\n")
    found = views.settings_view(store_paths, project="payments-api")
    assert "loop_maxx" in found.problem and found.values == {}
    assert found.file == "loop_maxx.simple: 3\n"


@pytest.fixture
def detected(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Provider detection without running any CLI: claude signed in, the rest signed out."""
    calls: list[str] = []

    def detector(paths: StorePaths) -> Callable[[str], ProviderStatus]:
        def detect(name: str) -> ProviderStatus:
            calls.append(name)
            signed = name == "claude"
            return ProviderStatus(
                name=name, installed=True, signed_in=signed, hint=f"run: {name} login"
            )

        return detect

    monkeypatch.setattr(agents, "detector", detector)
    monkeypatch.setattr(views, "_detected", {})
    return calls


def test_agents_sum_tokens_per_role_and_list_their_workflows(
    seeded: StorePaths, detected: list[str]
) -> None:
    event = step_end("aaaaaaa3", "codex", 700)
    journal.append(seeded, Event.model_validate({**event.model_dump(), "role": "implementer"}))
    found = views.agents_view(seeded, project="payments-api", window="all")
    roles = {role.role: role for role in found.roster}
    assert roles["implementer"].tokens == 700 and roles["planner"].tokens == 0
    assert roles["implementer"].used_in == ["simple", "standard", "critical"]
    assert roles["test-runner"].used_in == [] and roles["test-runner"].on is False
    assert roles["planner"].skill_file.endswith("roles/plan/SKILL.md")
    cards = {card.name: card for card in found.providers}
    assert cards["claude"].signed_in and cards["codex"].hint == "run: codex login"
    assert (cards["codex"].slots_used, cards["codex"].slots_total) == (1, 3)
    assert found.routing["simple"] == ["plan", "implement", "review_code"]


def test_provider_detection_is_reused_for_a_minute(seeded: StorePaths, detected: list[str]) -> None:
    views.agents_view(seeded, project=None, window="today")
    views.agents_view(seeded, project=None, window="today")
    assert detected.count("claude") == 1
    views.agents_view(seeded, project=None, window="today", refresh=True)
    assert detected.count("claude") == 2


def test_workflows_show_the_steps_that_would_run(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    configure.save_settings({"agents.code-reviewer.on": False}, project="payments-api", by="ui")
    found = views.workflows_view(store_paths, project="payments-api")
    assert found.names == ["simple", "standard", "critical"]
    assert found.workflows["simple"].on_fail == {"review_code": "implement"}
    assert found.effective["simple"] == ["plan", "implement"]
    assert found.loop_max == {"simple": 3, "standard": 4, "critical": 6}
    assert found.agents["planner"] == "claude/opus" and "approve" in found.library
    assert found.set_here == ["agents.code-reviewer.on"]
    assert "code-reviewer" in found.off and "test-runner" in found.off and found.plan_review
