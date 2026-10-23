"""Skills: role skill lookup and seeding, lint, install (SP4 spec decisions 2-7)."""

from pathlib import Path

from super_harness.model import SkillMeta
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
