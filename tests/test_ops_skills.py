"""Skills: role skill lookup and seeding, lint, install (SP4 spec decisions 2-7)."""

from pathlib import Path

import pytest

from super_harness.model import SkillMeta, UserError
from super_harness.model.settings import SkillCaps
from super_harness.ops import skills
from super_harness.store import StorePaths
from super_harness.store.frontmatter import split_frontmatter
from super_harness.store.seed import ensure_project, ensure_store


def role(folder: Path, name: str, body: str) -> None:
    (folder / name).mkdir(parents=True, exist_ok=True)
    text = f"---\nname: {name}\ndescription: Use when testing.\n---\n{body}"
    (folder / name / "SKILL.md").write_text(text, encoding="utf-8")


def test_every_role_has_a_skill() -> None:
    for name in skills.ROLES:
        meta, body = split_frontmatter((skills.roles_dir() / name / "SKILL.md").read_text())
        assert SkillMeta.model_validate(meta).name == name and body.strip()


def test_role_text_prefers_project_then_defaults_then_package(store_paths: StorePaths) -> None:
    ensure_store(store_paths)
    project = ensure_project(store_paths, "payments-api")
    packaged = split_frontmatter((skills.roles_dir() / "plan" / "SKILL.md").read_text())[1]
    assert skills.role_text(store_paths, "payments-api", "plan") == packaged
    role(store_paths.defaults / "roles", "plan", "Defaults plan.\n")
    assert skills.role_text(store_paths, "payments-api", "plan") == "Defaults plan.\n"
    role(project.root / "roles", "plan", "Project plan.\n")
    assert skills.role_text(store_paths, "payments-api", "plan") == "Project plan.\n"
    assert skills.role_text(store_paths, "payments-api", "no-such-role") is None


def test_init_seeds_role_skills_and_keeps_edits(store_paths: StorePaths) -> None:
    ensure_store(store_paths)
    seeded = sorted(path.name for path in (store_paths.defaults / "roles").iterdir())
    assert seeded == sorted(skills.ROLES)
    edited = store_paths.defaults / "roles" / "implement" / "SKILL.md"
    edited.write_text("---\nname: implement\ndescription: Use when mine.\n---\nMine.\n")
    ensure_store(store_paths)
    assert edited.read_text().endswith("Mine.\n")


COMMANDS = {"init", "wait", "plan", "plan new", "plan review", "memory", "memory add"}
CAPS = SkillCaps()
GOOD = """---
name: good-skill
description: Use when the user asks for a good skill.
---
0. Run `harness --version`; it prints `super-harness <version>`.
1. Run `harness plan new --title T` and `harness wait --timeout 540`.

```
harness plan review <id>
$ harness memory add "x" --why y
```
Read `references/rubric.md` when grading.
"""


def skill(folder: Path, name: str, text: str) -> Path:
    path = folder / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def problems(*targets: Path) -> list[str]:
    return [p.message for p in skills.lint(list(targets), commands=COMMANDS, caps=CAPS)]


def test_a_good_skill_is_clean(tmp_path: Path) -> None:
    path = skill(tmp_path, "good-skill", GOOD)
    (path.parent / "references").mkdir()
    (path.parent / "references" / "rubric.md").write_text("rubric")
    assert problems(tmp_path) == []


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("name: good-skill", "name: other", "name other does not match its folder good-skill"),
        (
            "description: Use when",
            "description: Helps when",
            'description must start with "Use when"',
        ),
        ("Run `harness --version`; it", "Check", "step 0 must run harness --version"),
        (
            "harness plan review <id>",
            "harness plan reveiw <id>",
            "unknown command: harness plan reveiw",
        ),
        ("`harness wait --timeout 540`", "`harness waitt`", "unknown command: harness waitt"),
    ],
)
def test_lint_names_each_problem(tmp_path: Path, old: str, new: str, message: str) -> None:
    path = skill(tmp_path, "good-skill", GOOD.replace(old, new))
    (path.parent / "references").mkdir()
    (path.parent / "references" / "rubric.md").write_text("rubric")
    assert problems(tmp_path) == [message]


def test_lint_checks_names_sizes_and_references(tmp_path: Path) -> None:
    description = "Use when " + "x" * 500
    long = GOOD.replace("Use when the user asks for a good skill.", description) + "word\n" * 80
    path = skill(tmp_path, "Bad_Name", long.replace("name: good-skill", "name: Bad_Name"))
    (path.parent / "references" / "nested").mkdir(parents=True)
    assert problems(path) == [
        "name must be lowercase words joined by single hyphens, at most 64 characters",
        f"description has {len(description)} characters; the cap is 500",
        f"{len(long.splitlines())} lines; the cap is 80",
        "references/rubric.md is missing",
        "references/ must not hold folders",
    ]


def test_role_skills_skip_the_installed_rules(tmp_path: Path) -> None:
    text = "---\nname: plan\ndescription: Plans.\n---\nPlan it.\n"
    skill(tmp_path / "roles", "plan", text)
    assert problems(tmp_path / "roles") == []
    skill(tmp_path / "roles", "bad", text)
    assert problems(tmp_path / "roles" / "bad") == ["name plan does not match its folder bad"]


def test_mentions_reads_code_spans_and_fenced_commands() -> None:
    assert skills.mentions(GOOD) == [
        [],
        ["plan", "new"],
        ["wait"],
        ["plan", "review"],
        ["memory", "add"],
    ]
    assert skills.mentions("Load `harness-memory` and the `harness store`.") == [["store"]]


ALPHA = "---\nname: alpha\ndescription: Use when alpha.\n---\n0. Run `harness --version`.\n"
BETA = (
    "---\nname: beta\ndescription: Use when beta.\n---\n"
    "The harness store keeps plans.\n\n```\nharness plan new --title T\n$ harness wait\n```\n"
    "Then `harness plan review <id>`.\n"
)


@pytest.fixture
def source(tmp_path: Path) -> Path:
    folder = tmp_path / "source"
    skill(folder, "alpha", ALPHA)
    skill(folder, "beta", BETA)
    (folder / "beta" / "references").mkdir()
    (folder / "beta" / "references" / "notes.md").write_text("notes\n")
    return folder


def test_install_writes_each_agents_folder_once(tmp_path: Path, source: Path) -> None:
    root = tmp_path / "repo"
    result = skills.install(["claude", "codex", "agy"], root=root, source=source)
    assert [(e.agent, e.name, e.state) for e in result.entries] == [
        ("claude", "alpha", "installed"),
        ("claude", "beta", "installed"),
        ("codex,antigravity", "alpha", "installed"),
        ("codex,antigravity", "beta", "installed"),
    ]
    assert (root / ".claude/skills/beta/references/notes.md").read_text() == "notes\n"
    assert (root / ".agents/skills/alpha/SKILL.md").read_text() == ALPHA


def test_install_twice_is_unchanged(tmp_path: Path, source: Path) -> None:
    skills.install(["claude"], root=tmp_path, source=source)
    again = skills.install(["claude"], root=tmp_path, source=source)
    assert {e.state for e in again.entries} == {"unchanged"} and not again.needs_yes


def test_a_hand_edited_skill_needs_yes_and_shows_a_diff(tmp_path: Path, source: Path) -> None:
    skills.install(["claude"], root=tmp_path, source=source)
    edited = tmp_path / ".claude/skills/alpha/SKILL.md"
    edited.write_text(ALPHA + "My own line.\n")
    held = skills.install(["claude"], root=tmp_path, source=source)
    assert held.needs_yes and edited.read_text().endswith("My own line.\n")
    (diff,) = held.diffs.values()
    assert "-My own line." in diff
    replaced = skills.install(["claude"], root=tmp_path, source=source, yes=True)
    assert [e.state for e in replaced.entries] == ["updated", "unchanged"]
    assert edited.read_text() == ALPHA


def test_cli_name_rewrites_commands_not_prose() -> None:
    renamed = skills.rename_cli(BETA, "hrn")
    assert "The harness store keeps plans." in renamed
    assert "\nhrn plan new --title T\n$ hrn wait\n" in renamed
    assert "`hrn plan review <id>`" in renamed and "`harness" not in renamed


def test_global_install_uses_each_agents_home_folder(tmp_path: Path, source: Path) -> None:
    result = skills.install(
        ["claude", "codex", "antigravity"], root=tmp_path, home=True, source=source
    )
    folders = sorted({str(e.folder.parent.relative_to(tmp_path)) for e in result.entries})
    assert folders == [".agents/skills", ".claude/skills", ".gemini/config/skills"]


def test_unknown_agents_are_refused(tmp_path: Path, source: Path) -> None:
    with pytest.raises(UserError, match="unknown agent gemini"):
        skills.install(["gemini"], root=tmp_path, source=source)
