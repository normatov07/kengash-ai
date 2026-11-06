"""Read models for the UI screens (SP5 spec §3)."""

import os
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from conftest import Engine

from kengash_ai import journal
from kengash_ai.model import (
    ConductorPing,
    Doc,
    Event,
    LoopLease,
    ProviderStatus,
    SlotEntry,
    SlotTable,
    Ticket,
    utc_now,
)
from kengash_ai.model.settings import SkillCaps
from kengash_ai.ops import agent_config, agents, configure, skills, views
from kengash_ai.ops.conductors import process_name
from kengash_ai.store import StorePaths, documents, runtime

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
    board = views.board(seeded, project=None)
    keys = [column.key for column in board.columns]
    assert keys == ["in_queue", "plan", "implement", "review_code", "security", "done"]
    assert board.steps == {"simple": 3, "standard": 4, "critical": 5}
    columns = {c.key: c for c in board.columns}
    assert [card.id for card in columns["in_queue"].cards] == ["aaaaaaa1", "aaaaaaa2"]
    assert [card.id for card in columns["implement"].cards] == ["aaaaaaa3"]
    assert [card.id for card in columns["security"].cards] == ["aaaaaaa4"]  # its gate's step
    assert columns["security"].cards[0].chip == "loop cap hit"
    assert [card.id for card in columns["done"].cards] == ["aaaaaaa5"]
    card: Any = columns["implement"].cards[0]
    assert (card.added, card.removed, card.provider, card.chip) == (130, 2, "codex", "")
    assert columns["in_queue"].cards[0].title == "<script>x</script>"  # escaped by the UI
    assert columns["in_queue"].cards[1].chip == "blocked"
    assert columns["done"].cards[0].done_at is not None


def test_board_footers_name_each_steps_sessions(seeded: StorePaths) -> None:
    columns = {c.key: c for c in views.board(seeded, project=None).columns}
    assert columns["plan"].footer == "planner · 0 sessions"
    assert columns["implement"].footer == "implementer · 1 session · codex 1/3 slots"
    assert columns["security"].footer == "security-reviewer · blocking gate"
    assert columns["in_queue"].footer == "" and columns["done"].footer == ""


def test_waiting_and_merge_ready_tickets_keep_a_step_column(
    seeded: StorePaths, make_ticket: Make
) -> None:
    project = seeded.project("payments-api")
    for doc in (
        make_ticket("bbbbbbb1", status="in_process/waiting_slot", step="review_code"),
        make_ticket("bbbbbbb2", status="in_process/awaiting_merge", workflow="simple"),
        make_ticket("bbbbbbb3", status="in_process/under_test", step="run_tests"),
    ):
        documents.save_ticket(project, doc)
    event = step_end("bbbbbbb1", "codex", 1)
    rejected = {**event.model_dump(), "step": "review_plan", "verdict": "fail"}
    journal.append(seeded, Event.model_validate(rejected))
    columns = {c.key: c for c in views.board(seeded, project=None).columns}
    review = {card.id: card for card in columns["review_code"].cards}
    assert review["bbbbbbb1"].chip == "waiting slot" and review["bbbbbbb1"].rejected == 1
    assert review["bbbbbbb2"].chip == "ready to merge"  # no step: its workflow's last
    assert [card.id for card in columns["run_tests"].cards] == ["bbbbbbb3"]  # shown once used


def test_links_report_each_projects_link_and_its_fix(
    registered_repo: Path, store_paths: StorePaths, tmp_path: Path, run_git: Callable[..., str]
) -> None:
    healthy = views.links(store_paths)
    (project,) = healthy.projects
    assert (project.state, project.memory, project.excluded, project.fix) == ("ok", "ok", True, "")
    assert (healthy.intact, healthy.total) == (1, 1)
    assert project.link == str(registered_repo / ".kengash")
    (registered_repo / ".kengash").unlink()
    broken = views.links(store_paths).projects[0]
    assert (broken.state, broken.fix, broken.hint) == ("missing", "repair", "kengash doctor --fix")
    (registered_repo / ".kengash").mkdir()
    real = views.links(store_paths).projects[0]
    assert (real.state, real.fix) == ("real folder", "adopt")
    assert real.hint == f"kengash adopt {registered_repo}"


def test_a_moved_repo_needs_a_relink(registered_repo: Path, store_paths: StorePaths) -> None:
    registered_repo.rename(registered_repo.with_name("moved"))
    moved = views.links(store_paths).projects[0]
    assert (moved.state, moved.fix) == ("repo missing", "relink")
    assert moved.hint == "kengash link payments-api <new-path>"
    assert views.overview(store_paths, window="today").links_broken == 1


def test_stores_found_beside_registered_repos_are_listed(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    other = registered_repo.parent / "legacy-crm" / ".kengash"
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
    assert found.repo_path == str(registered_repo / ".kengash" / "SETTINGS.md")
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
    roles = {agent.role: agent for agent in found.agents}
    assert roles["implementer"].tokens == 700 and roles["planner"].tokens == 0
    assert [use.workflow for use in roles["implementer"].used_in] == [
        "simple",
        "standard",
        "critical",
    ]
    assert roles["test-runner"].used_in == [] and roles["test-runner"].on is False
    assert roles["planner"].builtin and roles["planner"].instructions.startswith("# Planner")
    cards = {card.name: card for card in found.providers}
    assert cards["claude"].signed_in and cards["codex"].hint == "run: codex login"
    assert (cards["codex"].slots_used, cards["codex"].slots_total) == (1, 3)


def test_agents_view_lists_skills_models_and_caps(seeded: StorePaths, detected: list[str]) -> None:
    role_dir = seeded.project("payments-api").root / "roles" / "perf-reviewer"
    role_dir.mkdir(parents=True)
    (role_dir / "SKILL.md").write_text("---\nname: perf-reviewer\ndescription: x\n---\nFast.\n")
    found = views.agents_view(seeded, project="payments-api", window="all")
    sources = {skill.name: skill.source for skill in found.skills}
    assert sources["review-code"] == "package" and sources["perf-reviewer"] == "project"
    assert list(sources)[:7] == sorted(skills.ROLES)
    assert found.instruction_caps == list(agent_config.instruction_caps("x", SkillCaps()))
    assert {card.name: card.models for card in found.providers}["claude"] == []  # the fake detector


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
    assert (found.review_diff_only, found.sessions_reuse) == (True, True)
    assert found.blocking == ["security-reviewer"]


def test_a_sparse_ticket_renders_empty_sections(
    registered_repo: Path, store_paths: StorePaths, make_ticket: Make
) -> None:
    documents.save_ticket(store_paths.project("payments-api"), make_ticket("bbbbbbb1"))
    found = views.ticket_view(store_paths, "bbbbbbb1", project=None)
    assert (found.meta["id"], found.project, found.plan.found) == (
        "bbbbbbb1",
        "payments-api",
        False,
    )
    assert (found.changes, found.timeline, found.memory_writes, found.attach) == ([], [], [], "")
    assert (found.depends_on, found.blocks, found.siblings) == ([], [], [])
    assert found.sections["Scope"] == "Rotate keys." and "id: bbbbbbb1" in found.file
    assert found.store_path.endswith("tasks/in_queue/bbbbbbb1.md")
    assert found.repo_path == str(registered_repo / ".kengash/tasks/in_queue/bbbbbbb1.md")
    assert [step.step for step in found.chain][:2] == ["plan", "review_plan"]
    assert {step.state for step in found.chain} == {"pending"}
    assert found.grant == 2


def test_a_ticket_lists_what_it_blocks_and_its_timeline(
    registered_repo: Path, store_paths: StorePaths, make_ticket: Make
) -> None:
    project = store_paths.project("payments-api")
    documents.save_ticket(
        project,
        make_ticket("ccccccc1", status="in_process/under_review", step="review_code", loop=2),
    )
    documents.save_ticket(
        project, make_ticket("ccccccc2", status="in_queue/blocked", depends_on=["ccccccc1"])
    )
    for step, verdict in (("plan", "pass"), ("implement", "done")):
        event = step_end("ccccccc1", "codex", 300)
        data = {**event.model_dump(), "step": step, "verdict": verdict, "role": "implementer"}
        journal.append(store_paths, Event.model_validate(data))
    memo = Event.model_validate(
        {"type": "memory.write", "file": "MEMORY.md", "line": "x", "why": "from ccccccc1"}
    )
    journal.append(store_paths, memo)
    configure.save_settings({"loop_grant": 3}, project="payments-api", by="ui")
    found = views.ticket_view(store_paths, "ccccccc1", project="payments-api")
    assert found.grant == 3
    assert [(link.id, link.status) for link in found.blocks] == [("ccccccc2", "in_queue/blocked")]
    assert [link.id for link in found.siblings] == ["ccccccc2"]
    assert [(row.step, row.verdict, row.tokens) for row in found.timeline] == [
        ("plan", "pass", 300),
        ("implement", "done", 300),
    ]
    assert [write["why"] for write in found.memory_writes] == ["from ccccccc1"]
    states = {step.step: step.state for step in found.chain}
    assert states["plan"] == "done" and states["review_code"] == "running"
    assert states["security"] == "pending"
    assert {step.step: step.runs for step in found.chain}["plan"] == 1


def test_an_empty_store_has_an_empty_memory_view(store_paths: StorePaths) -> None:
    found = views.memory_view(store_paths, project=None)
    assert (found.ticket_files, found.index, found.writes, found.files) == (0, [], [], [])
    assert found.tickets == {"in_queue": 0, "in_process": 0, "done": 0}
    assert not found.compacting and found.memory_text == ""


def test_the_memory_view_counts_files_tickets_and_models(seeded: StorePaths) -> None:
    event = step_end("aaaaaaa3", "codex", 10)
    journal.append(seeded, Event.model_validate({**event.model_dump(), "model": "gpt-5-codex"}))
    compacted = {"type": "memory.compacted", "file": "MEMORY.md", "before": 210, "after": 150}
    journal.append(seeded, Event.model_validate({**compacted, "accepted": True}))
    found = views.memory_view(seeded, project="payments-api")
    assert found.ticket_files == 5 and found.tickets == {"in_queue": 2, "in_process": 2, "done": 1}
    names = [(file.name, file.scope) for file in found.files]
    assert names[:2] == [("MEMORY.md", "global"), ("DECISIONS.md", "global")]
    assert ("PROCESS.md", "project") in names and ("SETTINGS.md", "project") in names
    memory = found.files[0]
    assert memory.compacted is not None and memory.tokens == len(found.memory_text) // 4
    rows = {row.id: row for row in found.index}
    assert rows["aaaaaaa3"].models == ["claude", "codex", "codex/gpt-5-codex"]
    assert rows["aaaaaaa5"].closed is not None and rows["aaaaaaa1"].closed is None
    assert found.writes[0]["type"] == "memory.compacted"  # newest first
    assert memory.text == found.memory_text and memory.text.startswith("# MEMORY.md")
    assert (found.last_before, found.last_after) == (210, 150)
    assert found.cap == 200 and found.links.total == 1


def test_the_overview_counts_tickets_and_enabled_agents(seeded: StorePaths) -> None:
    found = views.overview(seeded, window="today")
    assert found.tickets_total == 5
    assert (found.agents_on, found.agents_total) == (5, 7)


@pytest.fixture
def tashkent(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The machine's clock at UTC+5, as on the user's laptop."""
    monkeypatch.setenv("TZ", "Asia/Tashkent")
    time.tzset()
    yield
    monkeypatch.delenv("TZ")
    time.tzset()


def test_today_is_the_machines_day_not_utcs(
    registered_repo: Path, store_paths: StorePaths, tashkent: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = store_paths
    local_morning = datetime(2026, 10, 24, 1, 0, tzinfo=UTC)  # 06:00 in Tashkent
    monkeypatch.setattr(views, "utc_now", lambda: local_morning)
    early = datetime(2026, 10, 23, 19, 30, tzinfo=UTC)  # 00:30 in Tashkent, the same local day
    late = datetime(2026, 10, 23, 18, 30, tzinfo=UTC)  # 23:30 the evening before
    for ts, ticket in ((early, "aaaaaaa3"), (late, "aaaaaaa2")):
        event = step_end(ticket, "codex", 100)
        journal.append(seeded, Event.model_validate({**event.model_dump(), "ts": ts}))
    assert views.overview(seeded, window="today").spend == {"codex": 100}


def test_the_overview_reports_gate_kinds_and_averages(seeded: StorePaths) -> None:
    state = runtime.load_ticket_state(seeded, "aaaaaaa4")
    state.approval = "loop_cap"
    runtime.save_ticket_state(seeded, "aaaaaaa4", state)
    found = views.overview(seeded, window="all")
    assert {gate.ticket: gate.kind for gate in found.gates} == {"aaaaaaa4": "loop_cap"}
    assert found.grant == 2
    assert found.avg_loops_done == 1.0  # aaaaaaa5 merged today at loop 1
    assert found.avg_ticket_cost == 0  # no done ticket spent tokens
    step = next(event for event in found.tail if event["type"] == "step.end")
    assert step["loop_max"] == 6  # the ticket's cap rides along for the journal line


def test_a_gate_at_its_loop_cap_reads_as_a_loop_cap(seeded: StorePaths) -> None:
    gates = {gate.ticket: gate.kind for gate in views.overview(seeded).gates}
    assert gates["aaaaaaa4"] == "loop_cap"  # loop 6 of 6, no approval recorded in its state


def test_agents_render_before_detection_runs(seeded: StorePaths, detected: list[str]) -> None:
    found = views.agents_view(seeded, project=None, window="today", detect=False)
    assert detected == [] and not any(card.checked for card in found.providers)
    # the fixed model names come without running any CLI, so pickers offer them at once
    models = {card.name: card.models for card in found.providers}
    assert models == {
        "claude": ["fable", "opus", "sonnet", "haiku"],
        "codex": [],
        "antigravity": [],
    }
    views.agents_view(seeded, project=None, window="today")  # detection runs and is kept
    again = views.agents_view(seeded, project=None, window="today", detect=False)
    assert all(card.checked for card in again.providers)
    assert {card.name: card.signed_in for card in again.providers}["claude"] is True


PERF_CHANGES: dict[str, Any] = {
    "agents.perf-reviewer": {"cli": "claude/sonnet", "skill": "perf-reviewer"},
    "steps.perf_review": {"role": "perf-reviewer", "kind": "review", "does": "Check hot paths."},
    "workflows.critical": {
        "steps": ["plan", "review_plan", "implement", "review_code", "perf_review", "security"],
        "on_fail": {
            "review_plan": "plan",
            "review_code": "implement",
            "perf_review": "implement",
            "security": "implement",
        },
    },
}


def test_custom_steps_reach_the_workflow_view(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    configure.save_settings(PERF_CHANGES, project="payments-api", by="ui")
    found = views.workflows_view(store_paths, project="payments-api")
    assert found.library[-1] == "perf_review" and found.library[0] == "plan"
    assert (found.kinds["perf_review"], found.kinds["implement"]) == ("review", "edit")
    assert found.roles["perf_review"] == "perf-reviewer"
    assert found.does == {"perf_review": "Check hot paths."}


def test_the_roster_marks_custom_agents(seeded: StorePaths, detected: list[str]) -> None:
    configure.save_settings(PERF_CHANGES, project="payments-api", by="ui")
    roles = {r.role: r for r in views.agents_view(seeded, project="payments-api").agents}
    perf = roles["perf-reviewer"]
    assert (perf.builtin, perf.step, [use.workflow for use in perf.used_in]) == (
        False,
        "perf_review",
        ["critical"],
    )
    assert (roles["planner"].builtin, roles["planner"].step) == (True, "plan")


def test_the_board_has_a_column_for_a_custom_step(seeded: StorePaths, make_ticket: Make) -> None:
    configure.save_settings(PERF_CHANGES, project="payments-api", by="ui")
    doc = make_ticket(
        "aaaaaaa6", status="in_process/perf_review", step="perf_review", workflow="critical"
    )
    documents.save_ticket(seeded.project("payments-api"), doc)
    columns = views.board(seeded, project="payments-api").columns
    keys = [column.key for column in columns]
    assert keys.index("perf_review") == keys.index("review_code") + 1 and keys[-1] == "done"
    perf = columns[keys.index("perf_review")]
    assert (perf.title, [card.id for card in perf.cards]) == ("Perf review", ["aaaaaaa6"])


def test_the_workflows_view_carries_each_importances_loop_cap(
    seeded: StorePaths, detected: list[str]
) -> None:
    found = views.workflows_view(seeded, project="payments-api")
    assert found.loop_max == {"simple": 3, "standard": 4, "critical": 6}


def test_a_custom_column_sits_where_its_workflow_runs_it(
    seeded: StorePaths, make_ticket: Make
) -> None:
    configure.save_settings(PERF_CHANGES, project="payments-api", by="ui")
    keys = [column.key for column in views.board(seeded, project="payments-api").columns]
    assert keys.index("perf_review") == keys.index("review_code") + 1
    assert keys.index("security") == keys.index("perf_review") + 1


def test_workflows_view_has_routing_and_picker(seeded: StorePaths) -> None:
    configure.save_settings(PERF_CHANGES, project="payments-api", by="ui")
    found = views.workflows_view(seeded, project="payments-api")
    assert found.routing == {"simple": "simple", "standard": "standard", "critical": "critical"}
    picks = {pick.step: pick for pick in found.picker}
    assert (picks["perf_review"].role, picks["perf_review"].kind, picks["perf_review"].builtin) == (
        "perf-reviewer",
        "review",
        False,
    )
    assert (picks["plan"].role, picks["plan"].builtin, picks["run_tests"].on) == (
        "planner",
        True,
        False,
    )
    assert (picks["approve"].role, picks["approve"].kind) == ("", "approve")


def test_the_overview_lists_live_loops_and_auto_mode(seeded: StorePaths) -> None:
    live = LoopLease(pid=os.getpid(), agent="claude", command=process_name(os.getpid()) or "")
    stale = LoopLease(
        pid=os.getppid(),
        agent="codex",
        project="payments-api",
        seen=datetime.now(UTC) - timedelta(hours=2),
    )
    runtime.save_lease(seeded, live)
    runtime.save_lease(seeded, stale)
    configure.save_settings({"loop_start": "auto"}, project="payments-api", by="test")
    found = views.overview(seeded, window="today")
    assert [(lease.pid, lease.scope, lease.mine) for lease in found.loops] == [
        (os.getpid(), "all projects", False)
    ]
    assert (found.auto_default, found.auto) == (False, {"payments-api": True})


def test_sessions_carry_activity(busy_ticket: Engine) -> None:
    (session,) = views.overview(busy_ticket.paths, window="today").sessions
    assert session.action == "reply: Rebrand core package and UI to Chess Samurai"
    assert (session.changed, session.quiet) == (1, False) and session.active_s is not None


def test_ticket_view_lists_in_progress_files(busy_ticket: Engine) -> None:
    found = views.ticket_view(busy_ticket.paths, busy_ticket.ticket_id, project=None)
    assert found.in_progress == ["lib/main.dart"]
    assert found.running is not None and found.running.provider == "antigravity"
