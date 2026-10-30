"""Skills: role skill lookup and seeding, lint, install (SP4 spec decisions 2-7, SP10 §3)."""

import json
import shutil
from pathlib import Path

import pytest

import kengash_ai
from kengash_ai.model import SkillMeta, UserError
from kengash_ai.model.settings import SkillCaps
from kengash_ai.ops import skills
from kengash_ai.store import StorePaths
from kengash_ai.store.frontmatter import split_frontmatter
from kengash_ai.store.seed import ensure_project, ensure_store


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
0. Run `kengash --version`; it prints `kengash-ai <version>`.
1. Run `kengash plan new --title T` and `kengash wait --timeout 540`.

```
kengash plan review <id>
$ kengash memory add "x" --why y
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
        ("Run `kengash --version`; it", "Check", "step 0 must run kengash --version"),
        (
            "kengash plan review <id>",
            "kengash plan reveiw <id>",
            "unknown command: kengash plan reveiw",
        ),
        ("`kengash wait --timeout 540`", "`kengash waitt`", "unknown command: kengash waitt"),
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
    assert skills.mentions("Load `kengash-memory` and the `kengash store`.") == [["store"]]


ALPHA = "---\nname: alpha\ndescription: Use when alpha.\n---\n0. Run `kengash --version`.\n"
BETA = (
    "---\nname: beta\ndescription: Use when beta.\n---\n"
    "The kengash store keeps plans; `/kengash:alpha` uses it.\n\n"
    "```\nkengash plan new --title T\n$ kengash wait\n```\n"
    "Then `kengash plan review <id>`.\n"
)


@pytest.fixture
def source(tmp_path: Path) -> Path:
    folder = tmp_path / "source"
    skill(folder, "alpha", ALPHA)
    skill(folder, "beta", BETA)
    (folder / "beta" / "references").mkdir()
    (folder / "beta" / "references" / "notes.md").write_text("notes\n")
    return folder


class FakeAgy:
    """`agy plugin install` as the spike saw it: the folder is copied into the plugins dir."""

    def __init__(self, home: Path, code: int = 0) -> None:
        self.home, self.code = home, code
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> int:
        self.calls.append(argv)
        if self.code == 0:
            target = self.home / ".gemini/config/plugins/kengash"
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(argv[-1], target)
        return self.code


def install(agents: list[str], root: Path, source: Path, **kw: object) -> skills.InstallResult:
    kw.setdefault("run", FakeAgy(root))
    kw.setdefault("user_home", root)
    return skills.install(agents, root=root, source=source, **kw)  # type: ignore[arg-type]


def test_claude_gets_a_skills_dir_plugin(tmp_path: Path, source: Path) -> None:
    result = install(["claude"], tmp_path, source)
    plugin = tmp_path / ".claude/skills/kengash"
    manifest = json.loads((plugin / ".claude-plugin/plugin.json").read_text())
    assert (manifest["name"], manifest["version"]) == ("kengash", kengash_ai.__version__)
    assert (plugin / "skills/alpha/SKILL.md").read_text() == ALPHA
    assert (plugin / "skills/beta/references/notes.md").read_text() == "notes\n"
    assert [(e.agent, e.name, e.state) for e in result.entries] == [
        ("claude", "alpha", "installed"),
        ("claude", "beta", "installed"),
    ]


def test_codex_gets_prefixed_copies(tmp_path: Path, source: Path) -> None:
    install(["codex"], tmp_path, source)
    assert (
        "name: kengash-alpha\n" in (tmp_path / ".agents/skills/kengash-alpha/SKILL.md").read_text()
    )
    text = (tmp_path / ".agents/skills/kengash-beta/SKILL.md").read_text()
    assert "name: kengash-beta\n" in text and "`$kengash-alpha`" in text and "/kengash:" not in text
    assert (tmp_path / ".agents/skills/kengash-beta/references/notes.md").is_file()


def test_agy_installs_the_plugin_and_falls_back(tmp_path: Path, source: Path) -> None:
    agy = FakeAgy(tmp_path)
    result = install(["agy"], tmp_path, source, run=agy)
    assert [(e.agent, e.name, e.state) for e in result.entries] == [
        ("antigravity", "kengash (plugin)", "installed")
    ]
    (argv,) = agy.calls
    assert argv[:3] == ["agy", "plugin", "install"]
    installed = tmp_path / ".gemini/config/plugins/kengash"
    assert (
        json.loads((installed / ".antigravity-plugin/plugin.json").read_text())["name"] == "kengash"
    )
    assert (installed / "skills/alpha/SKILL.md").read_text() == ALPHA
    assert not pathlib_exists(argv[-1])  # the build folder is temporary
    failed = install(["agy"], tmp_path / "other", source, run=FakeAgy(tmp_path / "other", 1))
    text = (tmp_path / "other/.agents/skills/kengash-beta/SKILL.md").read_text()
    assert "`/kengash-alpha`" in text and all(
        e.note == "agy plugin install failed; copies instead" for e in failed.entries
    )


def test_install_twice_is_unchanged(tmp_path: Path, source: Path) -> None:
    for agents in (["claude"], ["codex"], ["antigravity"]):
        install(agents, tmp_path, source)
        agy = FakeAgy(tmp_path)
        again = install(agents, tmp_path, source, run=agy)
        assert {e.state for e in again.entries} == {"unchanged"} and not again.needs_yes
        assert agy.calls == []


def test_a_hand_edited_skill_needs_yes_and_shows_a_diff(tmp_path: Path, source: Path) -> None:
    install(["claude"], tmp_path, source)
    edited = tmp_path / ".claude/skills/kengash/skills/alpha/SKILL.md"
    edited.write_text(ALPHA + "My own line.\n")
    held = install(["claude"], tmp_path, source)
    assert held.needs_yes and edited.read_text().endswith("My own line.\n")
    (diff,) = held.diffs.values()
    assert "-My own line." in diff
    replaced = install(["claude"], tmp_path, source, yes=True)
    assert [e.state for e in replaced.entries] == ["updated", "unchanged"]
    assert edited.read_text() == ALPHA


def test_cli_name_rewrites_commands_not_prose() -> None:
    renamed = skills.rename_cli(BETA, "/opt/kg/bin/kengash")
    assert "The kengash store keeps plans;" in renamed
    assert "\n/opt/kg/bin/kengash plan new --title T\n$ /opt/kg/bin/kengash wait\n" in renamed
    assert "`/opt/kg/bin/kengash plan review <id>`" in renamed and "`kengash" not in renamed


def test_global_install_uses_each_agents_home_folder(tmp_path: Path, source: Path) -> None:
    result = install(["claude", "codex", "antigravity"], tmp_path, source, home=True)
    folders = sorted(
        {str(e.folder.relative_to(tmp_path)).rsplit("/", 1)[0] for e in result.entries}
    )
    assert folders == [".agents/skills", ".claude/skills/kengash/skills", ".gemini/config/plugins"]


def test_unknown_agents_are_refused(tmp_path: Path, source: Path) -> None:
    with pytest.raises(UserError, match="unknown agent gemini"):
        skills.install(["gemini"], root=tmp_path, source=source)


def ours(folder: Path, name: str, source: str) -> Path:
    text = f"---\nname: {name}\ndescription: Use when.\nmetadata: {{source: {source}}}\n---\nOld.\n"
    return skill(folder, name, text)


def test_install_removes_old_names_of_ours_only(tmp_path: Path, source: Path) -> None:
    folder = tmp_path / ".claude/skills"
    ours(folder, "harness-memory", "super-harness")  # 0.1.0 shipped it under this name
    ours(folder, "to-loop", "kengash-ai")
    ours(folder, "theirs", "someone-else")
    ours(tmp_path / ".agents/skills", "to-loop", "kengash-ai")
    result = install(["claude", "codex"], tmp_path, source)
    removed = sorted((e.agent, e.name) for e in result.entries if e.state == "removed")
    assert removed == [("claude", "harness-memory"), ("claude", "to-loop"), ("codex", "to-loop")]
    assert (folder / "theirs" / "SKILL.md").is_file() and (folder / "kengash").is_dir()


def test_agy_plugin_keeps_codex_copies(tmp_path: Path, source: Path) -> None:
    install(["codex"], tmp_path, source)
    install(["antigravity"], tmp_path, source)
    assert (tmp_path / ".agents/skills/kengash-alpha/SKILL.md").is_file()


def test_installed_skills_are_the_six_short_names() -> None:
    found = {p.name for p in skills.packaged().iterdir() if (p / "SKILL.md").is_file()}
    assert found == {"plan", "grill", "ticket", "loop", "ui", "memory"}


OLD_COMMANDS = ("/to-plan", "/to-ticket", "/to-loop", "/open-ui", "/to-plan-with-grill")


def test_no_old_command_spelling_left() -> None:
    root = Path(__file__).resolve().parents[1]
    texts = [root / "README.md", *(root / "skills").rglob("*.md")]
    texts += (root / "src" / "kengash_ai" / "ui" / "static").rglob("*.js")
    stale = [
        str(path)
        for path in texts
        if any(old in path.read_text(encoding="utf-8") for old in OLD_COMMANDS)
    ]
    assert stale == []


def pathlib_exists(path: str) -> bool:
    return Path(path).exists()
