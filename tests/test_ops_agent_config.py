"""Custom agents through ops: one validated save, a starter skill, journaled (SP6 spec §3)."""

import contextlib
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import git

from kengash_ai import settings
from kengash_ai.model import Doc, Ticket, UserError
from kengash_ai.ops import agent_config, projects, skills
from kengash_ai.store import StorePaths, documents, locks
from kengash_ai.store.frontmatter import split_frontmatter

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
    assert "kengash: agent new perf-reviewer" in git(store_paths.home, "log", "--format=%s")


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


def test_agent_edits_read_settings_under_the_lock(
    registered_repo: Path, store_paths: StorePaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    real_locked, real_load = locks.locked, settings.load

    @contextlib.contextmanager
    def locked(path: Path) -> Iterator[None]:
        order.append("lock")
        with real_locked(path):
            yield
        order.append("unlock")

    def load(paths: StorePaths, slug: str | None = None) -> Any:
        order.append("load")
        return real_load(paths, slug)

    monkeypatch.setattr(agent_config, "locked", locked)
    monkeypatch.setattr(settings, "load", load)
    new_perf()
    agent_config.remove_agent("perf-reviewer", project="payments-api", by="cli")
    assert order == ["lock", "load", "unlock", "lock", "load", "unlock"]


Patch = agent_config.AgentPatch
OWN = "roles/perf-reviewer/SKILL.md"


def edit(project: str | None = "payments-api", **fields: Any) -> agent_config.AgentChange:
    return agent_config.edit_agent("perf-reviewer", Patch(**fields), project=project, by="cli")


def package_body(skill: str) -> str:
    return split_frontmatter((skills.roles_dir() / skill / "SKILL.md").read_text())[1]


def test_edit_changes_only_given_fields(registered_repo: Path, store_paths: StorePaths) -> None:
    new_perf()
    change = edit(cli="codex", on=False)
    assert change.keys == ["agents.perf-reviewer.cli", "agents.perf-reviewer.on"]
    agent = settings.load(store_paths, "payments-api").agents["perf-reviewer"]
    assert (agent.cli, agent.on, agent.skill, agent.blocking) == (
        "codex",
        False,
        "perf-reviewer",
        False,
    )


@pytest.mark.parametrize(
    ("field", "value"), [("kind", "read"), ("does", "x"), ("skill", "plan"), ("instructions", "x")]
)
def test_builtin_refuses_kind_does_skill_instructions(
    registered_repo: Path, store_paths: StorePaths, field: str, value: str
) -> None:
    before = scope_files(store_paths)
    message = f"planner is a built-in agent; its {field} is fixed; copy it to change what it does"
    with pytest.raises(UserError, match=re.escape(message)):
        fields: dict[str, Any] = {field: value}
        patch = Patch(**fields)
        agent_config.edit_agent("planner", patch, project=None, by="cli")
    assert scope_files(store_paths) == before


def test_builtin_takes_its_model_and_switches(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    patch = Patch(cli="claude/haiku", fallback=["antigravity"], on=False, blocking=True)
    agent_config.edit_agent("planner", patch, project=None, by="cli")
    agent_config.edit_agent("planner", Patch(bypass_permissions=True), project=None, by="cli")
    a = settings.load(store_paths).agents["planner"]
    found = (a.cli, a.fallback, a.on, a.blocking, a.bypass_permissions)
    assert found == ("claude/haiku", ["antigravity"], False, True, True)


def test_own_instructions_are_written_and_capped(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    new_perf()
    text = "You review for speed only.\n1. Read the diff.\n"
    change = edit(instructions=text)
    assert change.skill_file == str(store_paths.project("payments-api").root / OWN)
    assert skills.role_text(store_paths, "payments-api", "perf-reviewer") == text
    with pytest.raises(UserError, match=r"^instructions have \d+ lines; the cap is \d+$"):
        edit(instructions="word\n" * 200)
    with pytest.raises(UserError, match=r"^instructions have \d+ words; the cap is \d+$"):
        edit(instructions=" ".join(["word"] * 500))
    with pytest.raises(UserError, match=r"^instructions are empty$"):
        edit(instructions="  \n")
    assert skills.role_text(store_paths, "payments-api", "perf-reviewer") == text


def test_instructions_that_look_like_frontmatter_stay_body(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    new_perf()
    text = "---\nname: other\ndescription: x\n---\nBody.\n"
    edit(instructions=text)
    assert skills.role_text(store_paths, "payments-api", "perf-reviewer") == text
    written = (store_paths.project("payments-api").root / OWN).read_text()
    assert split_frontmatter(written)[0]["name"] == "perf-reviewer"


def test_use_a_skill_points_at_any_role_skill(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    new_perf()
    edit(skill="review-code")
    assert settings.load(store_paths, "payments-api").agents["perf-reviewer"].skill == "review-code"
    with pytest.raises(UserError, match=r"^no role skill nope$"):
        edit(skill="nope")


def test_kind_change_drops_review_edges(registered_repo: Path, store_paths: StorePaths) -> None:
    new_perf()
    change = edit(kind="read")
    assert set(change.keys) == {"steps.perf_review.kind", "workflows.critical"}
    resolved = settings.load(store_paths, "payments-api")
    assert "perf_review" not in resolved.workflows["critical"].on_fail
    assert resolved.workflows["critical"].steps[4] == "perf_review"
    assert resolved.steps["perf_review"].kind == "read"


def test_kind_change_refused_while_a_project_sends_back_from_it(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    agent_config.new_agent(
        "perf-reviewer", kind="review", does=DOES, step="perf_review", project=None, by="cli"
    )
    flow = settings.load(store_paths, "payments-api").workflows["critical"]
    whole = {
        "steps": [*flow.steps, "perf_review"],
        "on_fail": {**flow.on_fail, "perf_review": "implement"},
    }
    settings.set_values(store_paths, "payments-api", {"workflows.critical": whole})
    before = scope_files(store_paths)
    with pytest.raises(UserError, match="project payments-api"):
        edit(project=None, kind="read")
    assert scope_files(store_paths) == before


def test_editing_a_defaults_agent_from_a_project_overrides_there(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    agent_config.new_agent("perf-reviewer", kind="review", does=DOES, project=None, by="cli")
    before = scope_files(store_paths)
    edit(cli="codex", instructions="Mine.\n")
    assert scope_files(store_paths)["defaults"] == before["defaults"]
    assert settings.load(store_paths, "payments-api").agents["perf-reviewer"].cli == "codex"
    assert settings.load(store_paths).agents["perf-reviewer"].cli == "claude"
    assert (store_paths.project("payments-api").root / OWN).read_text().endswith("Mine.\n")
    assert "Mine." not in (store_paths.defaults / OWN).read_text()


def test_new_agent_takes_fallbacks_a_skill_or_instructions(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    new_perf(fallback=["antigravity"], instructions="Speed only.\n")
    resolved = settings.load(store_paths, "payments-api")
    assert resolved.agents["perf-reviewer"].fallback == ["antigravity"]
    assert skills.role_text(store_paths, "payments-api", "perf-reviewer") == "Speed only.\n"
    agent_config.new_agent(
        "deep-reviewer",
        kind="review",
        does=DOES,
        skill="review-code",
        project="payments-api",
        by="x",
    )
    assert settings.load(store_paths, "payments-api").agents["deep-reviewer"].skill == "review-code"
    assert not (store_paths.project("payments-api").root / "roles/deep-reviewer").exists()
    with pytest.raises(UserError, match=r"^pass a skill or instructions, not both$"):
        agent_config.new_agent(
            "x-reviewer",
            kind="read",
            does=DOES,
            skill="plan",
            instructions="x",
            project=None,
            by="x",
        )


def test_copy_builtin_makes_an_own_agent(registered_repo: Path, store_paths: StorePaths) -> None:
    change = agent_config.copy_agent("code-reviewer", "strict-reviewer", project=None, by="cli")
    assert (change.role, change.step) == ("strict-reviewer", "strict_reviewer")
    resolved = settings.load(store_paths)
    agent, source = resolved.agents["strict-reviewer"], resolved.agents["code-reviewer"]
    assert (agent.cli, agent.fallback, agent.skill) == (
        source.cli,
        source.fallback,
        "strict-reviewer",
    )
    step = resolved.steps["strict_reviewer"]
    assert (step.kind, step.does) == ("review", agent_config.BUILTIN_DOES["code-reviewer"])
    body = skills.role_text(store_paths, "payments-api", "strict-reviewer")
    assert body == package_body("review-code")
    assert (
        resolved.workflows["critical"].steps
        == settings.load(store_paths).workflows["critical"].steps
    )


def test_copy_refuses_test_runner_and_taken_names(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    with pytest.raises(
        UserError, match=r"^test-runner cannot be copied: it runs a shell check, not a model$"
    ):
        agent_config.copy_agent("test-runner", "my-tests", project=None, by="cli")
    with pytest.raises(UserError, match=r"^agent planner exists; pick another name$"):
        agent_config.copy_agent("code-reviewer", "planner", project=None, by="cli")


def test_describe_lists_where_used(registered_repo: Path, store_paths: StorePaths) -> None:
    new_perf()
    resolved = settings.load(store_paths, "payments-api")
    perf = agent_config.describe(store_paths, resolved, "payments-api", "perf-reviewer")
    found = (perf.builtin, perf.kind, perf.step, perf.provider, perf.model, perf.does)
    assert found == (False, "review", "perf_review", "claude", "sonnet", DOES)
    assert perf.used_in == [agent_config.UsedIn("critical", 5)]
    assert perf.instructions_own and perf.instructions.startswith("# Perf reviewer")
    planner = agent_config.describe(store_paths, resolved, "payments-api", "planner")
    assert (planner.builtin, planner.instructions_own, planner.kind, planner.step) == (
        True,
        False,
        "read",
        "plan",
    )
    assert planner.instructions == package_body("plan") and planner.model == "opus"
    assert [use.workflow for use in planner.used_in] == ["simple", "standard", "critical"]
    assert planner.does == agent_config.BUILTIN_DOES["planner"]


def test_new_agent_refuses_builtin_skill_names(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    """A role named like a built-in skill would run the package's skill, not its own text."""
    before = scope_files(store_paths)
    message = r"^review-security is the name of a built-in skill; pick another name$"
    with pytest.raises(UserError, match=message):
        agent_config.new_agent(
            "review-security", kind="review", does=DOES, instructions="Mine.", project=None, by="x"
        )
    with pytest.raises(UserError, match=r"^sync-docs is the name of a built-in skill"):
        agent_config.copy_agent("code-reviewer", "sync-docs", project=None, by="x")
    assert scope_files(store_paths) == before


def test_a_review_step_before_implement_gets_no_default_edge(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    agent_config.new_agent(
        "spec-reviewer",
        kind="review",
        does=DOES,
        workflows=["simple"],
        after="plan",
        project=None,
        by="x",
    )
    flow = settings.load(store_paths).workflows["simple"]
    assert flow.steps == ["plan", "spec_reviewer", "implement", "review_code"]
    assert "spec_reviewer" not in flow.on_fail
