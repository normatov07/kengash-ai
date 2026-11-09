"""Ticket graph shape, declared needs and hot files (SP18 spec §3.6, §3.7)."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from kengash_ai import gitops, scheduler
from kengash_ai.cli import app
from kengash_ai.model import PlanMode, UserError
from kengash_ai.model.settings import PathClaims
from kengash_ai.ops import plans, records, tickets
from kengash_ai.store import StorePaths

runner = CliRunner()
POLICY = scheduler.PathPolicy(tuple(PathClaims().shared), 0)
BATCH = """\
- key: core
  title: Core
  importance: standard
  touches: [lib/core/a.dart]
  provides: [Core.run() -> None]
- key: left
  title: Left
  importance: standard
  touches: [lib/left/a.dart, lib/shared/x.dart]
  depends_on: [core]
  needs: {core: the Core interface}
- key: right
  title: Right
  importance: standard
  touches: [lib/right/a.dart, lib/shared/x.dart]
  depends_on: [core]
  needs: {core: the Core interface}
- key: wide
  title: Wide
  importance: simple
  touches: [src/]
"""


@pytest.fixture
def engine_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "gitconfig"
    config.write_text("[user]\n\tname = Dev\n\temail = dev@example.com\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))


def plan_for(repo: Path) -> str:
    plan_id = plans.new_plan(
        "Do it.", title="P", mode=PlanMode.direct, project=None, cwd=repo, by="x"
    ).id
    plans.approve_plan(plan_id, skip_review=True, project=None, by="x")
    return plan_id


def test_shape_levels_and_widest() -> None:
    found = scheduler.shape({"a": [], "b": ["a"], "c": ["a"], "d": ["b", "c"]})
    assert (found.tickets, found.levels, found.widest) == (4, 3, 2)


def test_chokepoint_past_first_level() -> None:
    graph = {"a": [], "b": ["a"], "c": ["b"], "d": ["b"], "e": ["b"]}
    assert scheduler.shape(graph).chokepoints == (("b", 3),)


def test_first_level_is_not_a_chokepoint() -> None:
    assert scheduler.shape({"a": [], "b": ["a"], "c": ["a"], "d": ["a"]}).chokepoints == ()


def test_behind_ignores_unknown_and_survives_a_cycle() -> None:
    held = scheduler.behind({"a": ["zzz"], "b": ["a"], "c": ["d"], "d": ["c"]})
    assert held["a"] == {"b"} and held["c"] == {"d"} and held["d"] == {"c"}


def test_empty_graph_has_a_shape() -> None:
    assert scheduler.shape({}).levels == 0


def test_dependency_without_need_is_refused(registered_repo: Path) -> None:
    batch = BATCH.replace("  needs: {core: the Core interface}\n", "", 1)
    with pytest.raises(UserError, match="say in `needs` what it uses from core"):
        tickets.add_tickets(plan_for(registered_repo), batch, project=None, by="x")


def test_blank_need_is_refused(registered_repo: Path) -> None:
    batch = BATCH.replace("the Core interface", "' '", 1)
    with pytest.raises(UserError, match="needs"):
        tickets.add_tickets(plan_for(registered_repo), batch, project=None, by="x")


def test_need_for_something_not_a_dependency_is_refused(registered_repo: Path) -> None:
    batch = BATCH.replace("{core: the Core interface}", "{core: x, other: y}", 1)
    with pytest.raises(UserError, match="not a dependency"):
        tickets.add_tickets(plan_for(registered_repo), batch, project=None, by="x")


def test_needs_land_in_scope(store_paths: StorePaths, registered_repo: Path) -> None:
    batch = tickets.add_tickets(plan_for(registered_repo), BATCH, project=None, by="x")
    ids = {new.key: new.id for new in batch.tickets}
    _, path = records.locate_ticket(store_paths, ids["left"], None)
    assert f"Needs:\n- {ids['core']}: the Core interface" in path.read_text(encoding="utf-8")
    assert batch.shape is not None and batch.shape.widest == 2


def test_check_creates_nothing_and_reports(
    store_paths: StorePaths, registered_repo: Path, engine_git: None
) -> None:
    target = registered_repo / "lib" / "shared" / "x.dart"
    target.parent.mkdir(parents=True)
    for number in range(3):
        target.write_text(str(number), encoding="utf-8")
        ticket = f"0000000{number}-aaaa-4bbb-8ccc-dddddddddddd"
        gitops.commit_all(registered_repo, "kg: x", {f"{gitops.TRAILER}Ticket": ticket})
    plan_id = plan_for(registered_repo)
    report = tickets.check_batch(plan_id, BATCH, project=None)
    assert report.serial == []  # one shared file is inside paths.max_overlap
    assert ("wide", "src/") in report.broad
    assert [(name, n) for name, n, _ in report.hot] == [("lib/shared/x.dart", 3)]
    assert report.hot[0][2] == ["left", "right"]
    assert records.project_tickets(store_paths, report.project) == {}


def test_check_reports_serial_pairs_past_the_overlap_allowance(
    store_paths: StorePaths, registered_repo: Path
) -> None:
    settings = store_paths.project("payments-api").settings
    settings.write_text("paths.max_overlap: 0\n", encoding="utf-8")
    report = tickets.check_batch(plan_for(registered_repo), BATCH, project=None)
    assert ("left", "right", "lib/shared/x.dart") in report.serial


def test_cli_check_prints_findings(inside_registered_repo: Path, store_paths: StorePaths) -> None:
    result = runner.invoke(
        app, ["ticket", "add", "--plan", plan_for(inside_registered_repo), "--check"], input=BATCH
    )
    assert result.exit_code == 0
    assert "graph: 4 tickets, 2 levels, up to 2 at once" in result.stdout
    assert "too broad: wide claims src/" in result.stdout


def test_cli_add_prints_the_shape(inside_registered_repo: Path) -> None:
    result = runner.invoke(
        app, ["ticket", "add", "--plan", plan_for(inside_registered_repo)], input=BATCH
    )
    assert "graph: 4 tickets, 2 levels, up to 2 at once" in result.stdout


def test_hot_files_counts_tickets_not_commits(repo: Path, engine_git: None) -> None:
    def commit(name: str, ticket: str) -> None:
        with (repo / name).open("a", encoding="utf-8") as file:
            file.write(ticket)
        gitops.commit_all(repo, f"kg: {ticket}", {f"{gitops.TRAILER}Ticket": ticket})

    one, two, three = (f"0000000{n}-aaaa-4bbb-8ccc-dddddddddddd" for n in (1, 2, 3))
    for ticket in (one, one, one, two):
        commit("twice.txt", ticket)
    for ticket in (one, two, three):
        commit("thrice.txt", ticket)
    assert gitops.hot_files(repo, "HEAD") == [("thrice.txt", 3)]


def test_hot_files_ignores_commits_without_a_ticket(repo: Path, engine_git: None) -> None:
    (repo / "plain.txt").write_text("x", encoding="utf-8")
    gitops.commit_all(repo, "plain", {})
    assert gitops.hot_files(repo, "HEAD", at_least=1) == []


@pytest.mark.parametrize("root", ["test/", "tests/", "test", "tests"])
def test_test_root_claim_no_longer_clashes(root: str) -> None:
    assert not scheduler.clash([root, "lib/a.dart"], ["test/x_test.dart", "lib/b.dart"], POLICY)
    assert not scheduler.clash([root], [root], POLICY)


def test_same_test_file_still_clashes() -> None:
    assert scheduler.clash(["test/x_test.dart"], ["test/x_test.dart"], POLICY)
    assert scheduler.clash(["lib/"], ["lib/a.dart"], POLICY)


def test_broad_is_a_top_level_folder_only() -> None:
    assert scheduler.is_broad("lib/", POLICY) and scheduler.is_broad("src", POLICY)
    assert not scheduler.is_broad("lib/core/", POLICY)
    assert not scheduler.is_broad("README.md", POLICY)
    assert not scheduler.is_broad("test/", POLICY)
