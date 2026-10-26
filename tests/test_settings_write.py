"""Comment-preserving SETTINGS.md writes (SP5 spec decision 7): a save rewrites only the
entries it changes."""

import difflib
from pathlib import Path

import pytest

from super_harness import settings
from super_harness.model import UserError
from super_harness.store import StorePaths, yamledit
from super_harness.store.seed import ensure_project, ensure_store


@pytest.fixture
def project_file(store_paths: StorePaths) -> Path:
    ensure_store(store_paths)
    return ensure_project(store_paths, "app").settings


def changed(before: str, after: str) -> list[str]:
    """The lines a save removed (`- `) and added (`+ `)."""
    diff = difflib.ndiff(before.splitlines(), after.splitlines())
    return [line for line in diff if line.startswith(("- ", "+ "))]


def test_a_scalar_changes_only_its_line(store_paths: StorePaths, project_file: Path) -> None:
    before = project_file.read_text()
    assert settings.set_values(store_paths, "app", {"loop_max.simple": 5}) == ["loop_max.simple"]
    assert changed(before, project_file.read_text()) == [
        "- loop_max.simple: 3",
        "+ loop_max.simple: 5",
    ]
    assert settings.load(store_paths, "app").loop_max.simple == 5


def test_a_trailing_comment_stays_in_its_column(
    store_paths: StorePaths, project_file: Path
) -> None:
    settings.set_values(store_paths, "app", {"loop_grant": 3})
    assert "loop_grant: 3                 # loops added per approval" in project_file.read_text()


def test_a_leaf_inside_a_flow_map_changes_only_its_row(
    store_paths: StorePaths, project_file: Path
) -> None:
    before = project_file.read_text()
    settings.set_values(store_paths, "app", {"agents.implementer.cli": "claude/sonnet"})
    assert changed(before, project_file.read_text()) == [
        "-   implementer:       {on: true,  cli: codex,         skill: implement, "
        "fallback: [claude/sonnet]}",
        "+   implementer:       {on: true,  cli: claude/sonnet,         skill: implement, "
        "fallback: [claude/sonnet]}",
    ]
    assert settings.load(store_paths, "app").agents["implementer"].cli == "claude/sonnet"


def test_a_missing_key_is_appended_as_a_dotted_key(
    store_paths: StorePaths, project_file: Path
) -> None:
    project_file.write_text("# mine\nversion: 1\n")
    settings.set_values(store_paths, "app", {"merge.mode": "auto"})
    assert project_file.read_text() == "# mine\nversion: 1\nmerge.mode: auto\n"


def test_a_missing_key_joins_its_block(store_paths: StorePaths, project_file: Path) -> None:
    project_file.write_text("agents:\n  planner: {cli: claude}\n# end\nversion: 1\n")
    settings.set_values(store_paths, "app", {"agents.doc-writer.on": True})
    assert project_file.read_text() == (
        "agents:\n  planner: {cli: claude}\n  doc-writer.on: true\n# end\nversion: 1\n"
    )
    assert settings.load(store_paths, "app").agents["doc-writer"].on is True


def test_a_workflow_is_replaced_whole_on_one_line(
    store_paths: StorePaths, project_file: Path
) -> None:
    before = project_file.read_text()
    standard = {"steps": ["plan", "implement"], "on_fail": {}}
    settings.set_values(store_paths, "app", {"workflows.standard": standard})
    assert sorted(changed(before, project_file.read_text())) == [
        "+   standard: {steps: [plan, implement], on_fail: {}}",
        "-              on_fail: {review_plan: plan, review_code: implement}}",
        "-   standard: {steps: [plan, review_plan, implement, review_code],",
    ]
    assert settings.load(store_paths, "app").workflows["standard"].steps == ["plan", "implement"]


def test_none_removes_an_override(store_paths: StorePaths, project_file: Path) -> None:
    settings.set_values(store_paths, "app", {"loop_max.critical": 9})
    settings.set_values(store_paths, "app", {"loop_max.critical": None})
    assert "loop_max.critical" not in project_file.read_text()
    assert settings.load(store_paths, "app").loop_max.critical == 6


def test_strings_that_need_quotes_get_them(store_paths: StorePaths, project_file: Path) -> None:
    settings.set_values(store_paths, "app", {"project.test_cmd": "uv run pytest -q # all"})
    assert settings.load(store_paths, "app").project.test_cmd == "uv run pytest -q # all"
    settings.set_values(store_paths, "app", {"project.test_cmd": "true"})
    assert settings.load(store_paths, "app").project.test_cmd == "true"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"loop_max.simple": 0}, "loop_max.simple"),
        ({"workflows.simple": {"steps": ["plan"], "on_fail": {"review_code": "plan"}}}, "on_fail"),
        ({"loop_maxx.simple": 3}, "did you mean loop_max"),
        ({"workflows.simple.steps": ["plan"]}, "workflows.simple"),
    ],
)
def test_an_invalid_save_writes_nothing(
    store_paths: StorePaths, project_file: Path, changes: dict[str, object], message: str
) -> None:
    before = project_file.read_bytes()
    with pytest.raises(UserError, match=message):
        settings.set_values(store_paths, "app", changes)
    assert project_file.read_bytes() == before


def test_saves_of_different_keys_both_survive(store_paths: StorePaths, project_file: Path) -> None:
    settings.set_values(store_paths, "app", {"loop_max.simple": 5})
    settings.set_values(store_paths, "app", {"merge.mode": "branch"})
    resolved = settings.load(store_paths, "app")
    assert (resolved.loop_max.simple, resolved.merge.mode) == (5, "branch")


def test_the_defaults_scope_writes_the_defaults_file(store_paths: StorePaths) -> None:
    ensure_store(store_paths)
    settings.set_values(store_paths, None, {"sessions.max": 4})
    assert "sessions.max: 4" in (store_paths.defaults / "SETTINGS.md").read_text()


def test_scope_keys_lists_the_leaves_a_file_sets(
    store_paths: StorePaths, project_file: Path
) -> None:
    project_file.write_text("loop_max.simple: 3\nagents:\n  planner: {cli: claude}\n")
    project_file.write_text(project_file.read_text() + "workflows:\n  simple: {steps: [plan]}\n")
    assert settings.scope_keys(store_paths, "app") == [
        "loop_max.simple",
        "agents.planner.cli",
        "workflows.simple",
    ]


def test_none_inside_a_flow_map_removes_only_that_leaf(
    store_paths: StorePaths, project_file: Path
) -> None:
    settings.set_values(store_paths, "app", {"agents.implementer.fallback": None})
    expected = "  implementer:       {on: true, cli: codex, skill: implement}\n"
    assert expected in project_file.read_text()
    assert settings.load(store_paths, "app").agents["implementer"].fallback == ["claude/sonnet"]


def test_removing_the_last_entry_of_a_block_drops_the_block(
    store_paths: StorePaths, project_file: Path
) -> None:
    project_file.write_text("version: 1\nloop_max:\n  simple: 5\nmerge.mode: ask\n")
    settings.set_values(store_paths, "app", {"loop_max.simple": None})
    assert project_file.read_text() == "version: 1\nmerge.mode: ask\n"


def test_a_missing_scope_file_is_created_with_the_change(
    store_paths: StorePaths, project_file: Path
) -> None:
    project_file.unlink()
    settings.set_values(store_paths, "app", {"loop_max.simple": 5})
    assert project_file.read_text() == "loop_max.simple: 5\n"


def test_a_rewritten_entry_keeps_the_space_after_its_key(
    store_paths: StorePaths, project_file: Path
) -> None:
    simple = {"steps": ["plan", "implement"], "on_fail": {}}
    settings.set_values(store_paths, "app", {"workflows.simple": simple})
    assert "  simple:   {steps: [plan, implement], on_fail: {}}\n" in project_file.read_text()


@pytest.mark.parametrize(
    "changes",
    [
        {"loop_max.simple": 5},
        {"loop_grant": 3},
        {"agents.implementer.cli": "claude/sonnet"},
        {"workflows.standard": {"steps": ["plan", "implement"], "on_fail": {}}},
        {"providers.antigravity": {"allow_api_key": False}},
        {"loop_max.critical": None},
        {"agents.implementer.fallback": None},
    ],
)
def test_a_crlf_file_keeps_crlf_on_every_line(
    store_paths: StorePaths, project_file: Path, changes: dict[str, object]
) -> None:
    project_file.write_bytes(project_file.read_bytes().replace(b"\n", b"\r\n"))
    assert settings.set_values(store_paths, "app", changes) == list(changes)
    after = project_file.read_bytes()
    assert after.count(b"\n") == after.count(b"\r\n") and b"\r\r" not in after
    settings.load(store_paths, "app")


@pytest.mark.parametrize(
    ("text", "key", "value", "expected"),
    [
        ("version: 1\r\n", "merge.mode", "auto", "version: 1\r\nmerge.mode: auto\r\n"),
        ("version: 1\r\nmerge.mode: ask", "merge.mode", "auto", "version: 1\r\nmerge.mode: auto"),
        (
            "loop_max:\r\n  simple: 5",
            "loop_max.standard",
            4,
            "loop_max:\r\n  simple: 5\r\n  standard: 4",
        ),
        ("a: {x: 1}\r\nb: 2", "b", {"y": 3}, "a: {x: 1}\r\nb: {y: 3}"),
        ("a: 1\nb: 2\n", "c", 3, "a: 1\nb: 2\nc: 3\n"),
    ],
)
def test_an_edit_writes_the_text_s_own_line_ending(
    text: str, key: str, value: object, expected: str
) -> None:
    assert yamledit.set_key(text, key, value) == expected


def test_a_defaults_save_that_breaks_a_project_writes_nothing(
    store_paths: StorePaths, registered_repo: Path
) -> None:
    auditor = {"cli": "claude", "skill": "review-code"}
    settings.set_values(store_paths, None, {"agents.auditor": auditor})
    store_paths.project("payments-api").settings.write_text("agents.auditor.on: false\n")
    defaults = store_paths.defaults / "SETTINGS.md"
    before = defaults.read_bytes()
    with pytest.raises(UserError, match=r"project payments-api .*: agents\.auditor\.cli"):
        settings.set_values(store_paths, None, {"agents.auditor": None})
    assert defaults.read_bytes() == before


def test_a_project_already_invalid_does_not_block_defaults_saves(
    store_paths: StorePaths, registered_repo: Path
) -> None:
    store_paths.project("payments-api").settings.write_text("loop_max.simple: 0\n")
    assert settings.set_values(store_paths, None, {"sessions.max": 4}) == ["sessions.max"]
