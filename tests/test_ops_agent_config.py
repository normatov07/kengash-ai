"""Custom agents through ops: one validated save, a starter skill, journaled (SP6 spec §3)."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import git

from super_harness import settings
from super_harness.model import Doc, Ticket, UserError
from super_harness.ops import agent_config, projects, skills
from super_harness.store import StorePaths, documents

Events = Callable[[], list[dict[str, Any]]]
DOES = "Flag N+1 queries and hot loops in the changed code."


def new_perf(**fields: Any) -> agent_config.AgentChange:
    args: dict[str, Any] = {
        "kind": "review",
        "does": DOES,
        "cli": "claude/sonnet",
        "step": "perf_review",
        "workflows": ["critical"],
        "after": "review_code",
        "project": "payments-api",
        "by": "cli",
    } | fields
    return agent_config.new_agent("perf-reviewer", **args)


def scope_files(paths: StorePaths) -> dict[str, bytes]:
    files = {"defaults": paths.defaults / "SETTINGS.md"}
    files |= {slug: paths.project(slug).settings for slug in ("payments-api", "web-dashboard")}
    return {name: path.read_bytes() for name, path in files.items() if path.is_file()}


def test_new_agent_writes_one_valid_save_and_a_starter_skill(
    registered_repo: Path, store_paths: StorePaths, journal_events: Events
) -> None:
    change = new_perf()
    assert (change.role, change.step) == ("perf-reviewer", "perf_review")
    assert change.keys == ["agents.perf-reviewer", "steps.perf_review", "workflows.critical"]
    resolved = settings.load(store_paths, "payments-api")
    critical = resolved.workflows["critical"]
    assert critical.steps == [
        "plan",
        "review_plan",
        "implement",
        "review_code",
        "perf_review",
        "security",
    ]
    assert critical.on_fail["perf_review"] == "implement"
    assert resolved.agents["perf-reviewer"].cli == "claude/sonnet"
    skill = Path(change.skill_file)
    assert skill == store_paths.project("payments-api").root / "roles/perf-reviewer/SKILL.md"
    assert skill.read_text(encoding="utf-8").startswith("---\nname: perf-reviewer\n")
    assert DOES in skill.read_text(encoding="utf-8")
    assert skills.lint([skill.parent.parent], commands=set(), caps=resolved.skill) == []
    event = journal_events()[-1]
    assert (event["type"], event["keys"], event["by"]) == (
        "settings.changed",
        change.keys,
        "cli",
    )
    assert "harness: agent new perf-reviewer" in git(store_paths.home, "log", "--format=%s")


def test_an_existing_skill_is_kept(registered_repo: Path, store_paths: StorePaths) -> None:
    mine = store_paths.defaults / "roles" / "perf-reviewer" / "SKILL.md"
    mine.parent.mkdir(parents=True)
    mine.write_text("---\nname: perf-reviewer\ndescription: mine\n---\nMine.\n", encoding="utf-8")
    assert new_perf().skill_file == ""
    assert mine.read_text(encoding="utf-8").endswith("Mine.\n")


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"role": "security-reviewer"}, "exists"),
        ({"role": "plan_reviewer", "step": "x_review"}, "role name"),
        ({"role": "perf--reviewer", "step": "x_review"}, "role name"),
        ({"step": "security"}, "exists"),
        ({"workflows": ["huge"]}, "unknown workflow huge"),
        ({"after": "docs"}, "has no step docs"),
        ({"kind": "read", "send_back": "implement"}, "only a review step"),
        ({"does": "two\nlines"}, "one line"),
    ],
)
def test_new_agent_refuses_without_writing(
    registered_repo: Path, store_paths: StorePaths, fields: dict[str, Any], message: str
) -> None:
    before = scope_files(store_paths)
    role = fields.pop("role", "perf-reviewer")
    args: dict[str, Any] = {
        "kind": "review",
        "does": DOES,
        "workflows": ["critical"],
        "project": "payments-api",
        "by": "cli",
    } | fields
    with pytest.raises(UserError, match=message):
        agent_config.new_agent(role, **args)
    assert scope_files(store_paths) == before
    assert not (store_paths.project("payments-api").root / "roles").exists()


def test_the_step_defaults_to_the_role_name(registered_repo: Path, store_paths: StorePaths) -> None:
    change = agent_config.new_agent(
        "perf-reviewer", kind="read", does=DOES, project="payments-api", by="cli"
    )
    assert (change.step, change.keys) == (
        "perf_reviewer",
        ["agents.perf-reviewer", "steps.perf_reviewer"],
    )


def test_does_round_trips_yaml_specials(registered_repo: Path, store_paths: StorePaths) -> None:
    does = 'Flag "N+1" queries: {hot: paths} # not a comment'
    new_perf(does=does)
    assert settings.load(store_paths, "payments-api").steps["perf_review"].does == does


def test_a_project_agent_touches_only_that_project(
    registered_repo: Path, store_paths: StorePaths, tmp_path: Path
) -> None:
    other = tmp_path / "code" / "web-dashboard"
    other.mkdir(parents=True)
    git(other, "init", "-q", "-b", "main")
    git(other, "commit", "-q", "--allow-empty", "-m", "init")
    projects.init_project(other)
    before = scope_files(store_paths)
    new_perf()
    after = scope_files(store_paths)
    assert after["defaults"] == before["defaults"]
    assert after["web-dashboard"] == before["web-dashboard"]
    assert after["payments-api"] != before["payments-api"]


def test_remove_agent_cleans_workflows_and_edges(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    before = settings.load(store_paths, "payments-api").workflows["critical"]
    new_perf()
    change = agent_config.remove_agent("perf-reviewer", project="payments-api", by="cli")
    assert change.keys == ["agents.perf-reviewer", "steps.perf_review", "workflows.critical"]
    resolved = settings.load(store_paths, "payments-api")
    assert "perf-reviewer" not in resolved.agents and resolved.steps == {}
    assert resolved.workflows["critical"] == before
    skill = store_paths.project("payments-api").root / "roles/perf-reviewer/SKILL.md"
    assert skill.is_file()  # the user's skill stays


def test_remove_refuses_built_ins_and_busy_steps(
    registered_repo: Path, store_paths: StorePaths, make_ticket: Callable[..., Doc[Ticket]]
) -> None:
    with pytest.raises(UserError, match="built-in role; switch it off instead"):
        agent_config.remove_agent("code-reviewer", project="payments-api", by="cli")
    new_perf()
    busy = make_ticket(status="in_process/perf_review", step="perf_review")
    documents.save_ticket(store_paths.project("payments-api"), busy)
    with pytest.raises(UserError, match="ticket 7b55e0c1 is at step perf_review; move it first"):
        agent_config.remove_agent("perf-reviewer", project="payments-api", by="cli")
    with pytest.raises(UserError, match="no agent perf-reviewer"):
        agent_config.remove_agent("perf-reviewer", project=None, by="cli")


def test_remove_names_where_an_inherited_agent_is_set(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    agent_config.new_agent("qa-helper", kind="read", does=DOES, project=None, by="cli")
    with pytest.raises(UserError, match="qa-helper is not set in payments-api; remove it where"):
        agent_config.remove_agent("qa-helper", project="payments-api", by="cli")
    assert agent_config.remove_agent("qa-helper", project=None, by="cli").keys == [
        "agents.qa-helper",
        "steps.qa_helper",
    ]
