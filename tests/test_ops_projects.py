import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from kengash_ai.model import Doc, Folder, NeedsSetup, Ticket, UserError
from kengash_ai.ops import projects, providers
from kengash_ai.store import StorePaths, documents, links
from kengash_ai.store.paths import ProjectPaths
from kengash_ai.store.registry import load_registry

MakeTicket = Callable[..., Doc[Ticket]]
NEWER = datetime(2026, 10, 23, 8, 0, tzinfo=UTC)


def test_init_registers_links_and_seeds(
    store_paths: StorePaths, repo: Path, run_git: Callable[..., str]
) -> None:
    result = projects.init_project(repo)
    project = store_paths.project("payments-api")
    assert (result.slug, result.created, result.warnings) == ("payments-api", True, [])
    assert (repo / ".kengash").resolve() == project.root.resolve()
    assert (repo / ".kengash" / "SETTINGS.md").is_file()
    assert (repo / ".kengash" / "memory" / "MEMORY.md").is_file()
    assert links.is_excluded(repo) is True
    assert load_registry(store_paths).projects["payments-api"].path == repo
    assert "kengash: init payments-api" in run_git(store_paths.home, "log", "--format=%s")


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


@pytest.mark.parametrize("name", [".kengash", ".harness"])
def test_init_refuses_a_real_store_folder(store_paths: StorePaths, repo: Path, name: str) -> None:
    (repo / name).mkdir()  # .harness: a real folder from before 0.2.0
    with pytest.raises(NeedsSetup, match=f"{name} is a real folder; run: harness adopt"):
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
    (repo / ".kengash").unlink()
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
    stray = tmp_path / "code" / "legacy-crm" / ".kengash"
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
    (repo / ".kengash").unlink()
    foreign = ProjectPaths(repo / ".kengash")
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
    (repo / ".kengash").mkdir()
    (repo / ".kengash" / "SETTINGS.md").write_text("version: 1\n", encoding="utf-8")
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


def test_doctor_warns_about_a_foreign_kengash(
    registered_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    foreign = tmp_path / "foreign-bin"
    foreign.mkdir()
    script = foreign / "kengash"
    script.write_text("#!/bin/sh\necho 'kengash 2.1.0'\n")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{foreign}{os.pathsep}{os.environ['PATH']}")
    assert providers.cli_clash() == (
        f"the first kengash on PATH ({script}) is not kengash-ai; put kengash-ai's first on "
        "PATH, or install skills with --cli-name set to its full path"
    )
    report = projects.doctor(fix=False, scan=None)
    assert any(p.warning and "not kengash-ai" in p.message for p in report.problems)


@pytest.mark.parametrize("banner", ["kengash-ai 0.1.0", "kengash-ai 0.2.0"])
def test_a_kengash_of_ours_is_fine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, banner: str
) -> None:
    ours = tmp_path / "older-bin"
    ours.mkdir()
    script = ours / "kengash"
    script.write_text(f"#!/bin/sh\necho '{banner}'\n")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{ours}{os.pathsep}{os.environ['PATH']}")
    assert providers.cli_clash() is None


def test_our_own_harness_or_none_is_fine(monkeypatch: pytest.MonkeyPatch) -> None:
    assert providers.cli_clash() is None  # the venv's harness comes first in tests
    monkeypatch.setenv("PATH", "/nonexistent")
    assert providers.cli_clash() is None


def test_doctor_checks_and_repairs_the_projects_memory_link(
    store_paths: StorePaths, registered_repo: Path
) -> None:
    link = store_paths.project("payments-api").memory_link
    link.unlink()
    report = projects.doctor(fix=False, scan=None)
    assert any(
        p.message == "memory link missing; run: harness doctor --fix" for p in report.problems
    )
    fixed = projects.doctor(fix=True, scan=None)
    assert any(p.message == "memory link missing; repaired" for p in fixed.problems)
    assert link.is_symlink() and link.resolve() == store_paths.memory.resolve()
    assert (registered_repo / ".kengash" / "memory" / "MEMORY.md").is_file()


def test_a_real_memory_folder_in_a_project_is_reported_not_replaced(
    store_paths: StorePaths, registered_repo: Path
) -> None:
    link = store_paths.project("payments-api").memory_link
    link.unlink()
    link.mkdir()
    (link / "notes.md").write_text("mine\n")
    report = projects.doctor(fix=True, scan=None)
    assert any("memory is a real folder" in p.message for p in report.problems)
    assert (link / "notes.md").read_text() == "mine\n"


def test_doctor_fix_prunes_old_logs(store_paths: StorePaths, repo: Path) -> None:
    projects.init_project(repo)
    store_paths.logs.mkdir(parents=True, exist_ok=True)
    old = store_paths.logs / "7b55e0c1-1.out"
    old.write_text("x")
    os.utime(old, (time.time() - 40 * 86400,) * 2)
    projects.doctor()
    assert old.exists()  # a plain check removes nothing
    projects.doctor(fix=True)
    assert not old.exists()


def test_init_writes_a_kengash_link(store_paths: StorePaths, repo: Path) -> None:
    result = projects.init_project(repo)
    assert (repo / ".kengash").is_symlink() and not (repo / ".harness").exists()
    assert (repo / ".kengash").resolve() == store_paths.project(result.slug).root.resolve()
    assert "/.kengash" in (repo / ".git" / "info" / "exclude").read_text().splitlines()


def test_doctor_replaces_a_legacy_harness_link(store_paths: StorePaths, repo: Path) -> None:
    root = store_paths.project(projects.init_project(repo).slug).root
    (repo / ".kengash").unlink()
    (repo / ".harness").symlink_to(root, target_is_directory=True)  # how 0.1.0 linked it
    found = projects.doctor().problems
    assert any("legacy .harness link" in p.message and not p.fixed for p in found)
    projects.doctor(fix=True)
    assert (repo / ".kengash").resolve() == root.resolve() and not (repo / ".harness").exists()
    assert projects.doctor().problems == []


def test_a_foreign_harness_link_is_left_alone(
    store_paths: StorePaths, repo: Path, tmp_path: Path
) -> None:
    projects.init_project(repo)
    (tmp_path / "theirs").mkdir()
    (repo / ".harness").symlink_to(tmp_path / "theirs", target_is_directory=True)
    projects.doctor(fix=True)
    assert (repo / ".harness").is_symlink()  # not ours: it points somewhere else


@pytest.mark.parametrize("name", [".kengash", ".harness"])
def test_adopt_and_the_scan_take_either_real_folder(
    store_paths: StorePaths, repo: Path, name: str
) -> None:
    (repo / name).mkdir()
    (repo / name / "SETTINGS.md").write_text("loop_grant: 3\n")
    assert projects.real_folders(repo.parent, 1) == [repo / name]
    result = projects.adopt(repo)
    assert (repo / ".kengash").is_symlink() and not (repo / ".harness").exists()
    assert (store_paths.project(result.slug).settings).read_text() == "loop_grant: 3\n"
