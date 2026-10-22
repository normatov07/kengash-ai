from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from super_harness.model import Doc, Folder, NeedsSetup, Ticket, UserError
from super_harness.ops import projects
from super_harness.store import StorePaths, documents, links
from super_harness.store.paths import ProjectPaths
from super_harness.store.registry import load_registry

MakeTicket = Callable[..., Doc[Ticket]]
NEWER = datetime(2026, 10, 23, 8, 0, tzinfo=UTC)


def test_init_registers_links_and_seeds(
    store_paths: StorePaths, repo: Path, run_git: Callable[..., str]
) -> None:
    result = projects.init_project(repo)
    project = store_paths.project("payments-api")
    assert (result.slug, result.created, result.warnings) == ("payments-api", True, [])
    assert (repo / ".harness").resolve() == project.root.resolve()
    assert (repo / ".harness" / "SETTINGS.md").is_file()
    assert (repo / ".harness" / "memory" / "MEMORY.md").is_file()
    assert links.is_excluded(repo) is True
    assert load_registry(store_paths).projects["payments-api"].path == repo
    assert "harness: init payments-api" in run_git(store_paths.home, "log", "--format=%s")


def test_init_is_idempotent_and_keeps_edits(store_paths: StorePaths, repo: Path) -> None:
    projects.init_project(repo)
    settings = store_paths.project("payments-api").settings
    settings.write_text("# edited\n", encoding="utf-8")
    again = projects.init_project(repo)
    assert (again.slug, again.created) == ("payments-api", False)
    assert settings.read_text(encoding="utf-8") == "# edited\n"


def test_init_from_a_subfolder_registers_the_repo_root(store_paths: StorePaths, repo: Path) -> None:
    (repo / "src").mkdir()
    assert projects.init_project(repo / "src").repo == repo


def test_init_refuses_a_real_harness_folder(store_paths: StorePaths, repo: Path) -> None:
    (repo / ".harness").mkdir()
    with pytest.raises(NeedsSetup, match="harness adopt"):
        projects.init_project(repo)


def test_plain_folder_is_registered_with_a_warning(store_paths: StorePaths, tmp_path: Path) -> None:
    folder = tmp_path / "notes"
    folder.mkdir()
    result = projects.init_project(folder)
    assert result.warnings == ["not a git repository: ticket worktrees will need git"]


def test_doctor_is_quiet_for_a_healthy_store(store_paths: StorePaths, repo: Path) -> None:
    projects.init_project(repo)
    report = projects.doctor()
    assert (report.projects, report.problems) == (1, [])


def test_doctor_without_a_store_says_so(store_paths: StorePaths) -> None:
    [problem] = projects.doctor().problems
    assert problem.message == f"no store at {store_paths.home}; run: harness init"


def test_moved_repo_is_reported_and_relinked(store_paths: StorePaths, repo: Path) -> None:
    projects.init_project(repo)
    moved = repo.with_name("payments")
    repo.rename(moved)
    [problem] = projects.doctor().problems
    assert problem.message.startswith(f"repo missing at {repo}")
    result = projects.relink("payments-api", moved)
    assert result.repo == moved
    assert projects.doctor().problems == []


def test_relink_needs_a_known_slug(store_paths: StorePaths, repo: Path) -> None:
    with pytest.raises(UserError, match="unknown project: nope"):
        projects.relink("nope", repo)


def test_doctor_fix_repairs_a_broken_link(store_paths: StorePaths, repo: Path) -> None:
    projects.init_project(repo)
    (repo / ".harness").unlink()
    [problem] = projects.doctor().problems
    assert problem.message == "link missing; run: harness doctor --fix"
    [fixed] = projects.doctor(fix=True).problems
    assert (fixed.message, fixed.fixed) == ("link missing; repaired", True)
    assert projects.doctor().problems == []


def test_doctor_reports_invalid_documents(store_paths: StorePaths, repo: Path) -> None:
    projects.init_project(repo)
    bad = store_paths.project("payments-api").folder(Folder.in_queue) / "deadbeef.md"
    bad.write_text("no frontmatter", encoding="utf-8")
    [problem] = projects.doctor().problems
    expected = "projects/payments-api/tasks/in_queue/deadbeef.md: document has no frontmatter"
    assert problem.message == expected


def test_doctor_scan_finds_unmanaged_stores(
    store_paths: StorePaths, repo: Path, tmp_path: Path
) -> None:
    projects.init_project(repo)
    stray = tmp_path / "code" / "legacy-crm" / ".harness"
    stray.mkdir(parents=True)
    messages = [problem.message for problem in projects.doctor(scan=tmp_path / "code").problems]
    found = stray.resolve()
    assert messages == [f"unmanaged store {found}; run: harness adopt {found.parent}"]


def test_adopt_merges_by_uuid_and_archives_everything(
    store_paths: StorePaths, repo: Path, make_ticket: MakeTicket
) -> None:
    projects.init_project(repo)
    project = store_paths.project("payments-api")
    shared = uuid4()
    documents.save_ticket(project, make_ticket("a1111111", uuid=shared, title="older"))
    (repo / ".harness").unlink()
    foreign = ProjectPaths(repo / ".harness")
    documents.save_ticket(
        foreign, make_ticket("a1111111", uuid=shared, title="newer", updated=NEWER)
    )
    documents.save_ticket(foreign, make_ticket("b2222222"))
    (foreign.root / "PROCESS.md").write_text("# foreign process\n", encoding="utf-8")

    result = projects.adopt(repo)

    assert (result.added, result.conflicts) == (1, 1)
    merged = documents.find_ticket(project, "a1111111")
    assert merged is not None
    assert documents.load_ticket(merged).meta.title == "newer"
    assert documents.find_ticket(project, "b2222222") is not None
    assert (result.archive / "replaced" / "a1111111.md").is_file()
    assert (result.archive / "original" / "tasks" / "in_queue" / "b2222222.md").is_file()
    assert project.process.read_text(encoding="utf-8") != "# foreign process\n"
    assert links.link_state(repo, project.root) is links.LinkState.ok


def test_adopting_a_new_project_takes_its_settings(store_paths: StorePaths, repo: Path) -> None:
    (repo / ".harness").mkdir()
    (repo / ".harness" / "SETTINGS.md").write_text("version: 1\n", encoding="utf-8")
    result = projects.adopt(repo)
    assert store_paths.project(result.slug).settings.read_text(encoding="utf-8") == "version: 1\n"
    assert (result.added, result.conflicts) == (0, 0)


def test_adopt_needs_a_real_folder(store_paths: StorePaths, repo: Path) -> None:
    with pytest.raises(UserError, match="nothing to adopt"):
        projects.adopt(repo)


def test_relink_refuses_a_path_registered_under_another_slug(
    store_paths: StorePaths, repo: Path, tmp_path: Path, run_git: Callable[..., str]
) -> None:
    projects.init_project(repo)
    other = tmp_path / "code" / "web"
    other.mkdir()
    run_git(other, "init", "-q", "-b", "main")
    projects.init_project(other)
    with pytest.raises(UserError, match="already registered as web"):
        projects.relink("payments-api", other)
