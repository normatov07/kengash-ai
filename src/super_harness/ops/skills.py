"""Skills (SP4 spec decisions 2 to 7): role skills for worker prompts; lint and install of
the installed skills."""

import re
from collections.abc import Collection, Iterator, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from pydantic import ValidationError

import super_harness
from super_harness import settings
from super_harness.model import HarnessError, SkillMeta, UserError
from super_harness.model.settings import SkillCaps
from super_harness.model.skills import DESCRIPTION_MAX, NAME_MAX, NAME_PATTERN
from super_harness.store.frontmatter import split_frontmatter
from super_harness.store.paths import StorePaths

ROLES = (
    "plan",
    "review-plan",
    "implement",
    "review-code",
    "review-security",
    "run-tests",
    "sync-docs",
)


def roles_dir() -> Path:
    """The package's role skills, `super_harness/roles/<role>/SKILL.md`."""
    return Path(str(resources.files("super_harness") / "roles"))


def role_text(paths: StorePaths, slug: str, skill: str) -> str | None:
    """The body of a role skill: the project's, else the defaults', else the package's."""
    for folder in (paths.project(slug).root / "roles", paths.defaults / "roles", roles_dir()):
        path = folder / skill / "SKILL.md"
        if path.is_file():
            try:
                return split_frontmatter(path.read_text(encoding="utf-8"))[1]
            except UserError:
                return path.read_text(encoding="utf-8")  # a hand-written file without frontmatter
    return None


SPAN = re.compile(r"`([^`\n]+)`")
FENCE = "```"
REFERENCE = re.compile(r"references/([\w.-]+)")
STOP = ("-", "<", "{", "'", '"', "[", "|", "&", ";", "$(", "#")


@dataclass
class Problem:
    path: str
    message: str


def packaged() -> Path:
    """The installed skills: the package's `skills/` (wheel), else the checkout's."""
    inside = Path(str(resources.files("super_harness") / "skills"))
    if inside.is_dir():
        return inside
    return Path(super_harness.__file__).resolve().parents[2] / "skills"


def lint_skills(targets: Sequence[Path], *, commands: Collection[str]) -> list[Problem]:
    """`harness skills lint`: the given targets, else the installed and role skills, with
    the user's `skill.*` caps (the package's when there is no store)."""
    try:
        caps = settings.load(StorePaths.default()).skill
    except HarnessError:
        caps = SkillCaps()
    return lint(list(targets) or [packaged(), roles_dir()], commands=commands, caps=caps)


def lint(targets: Sequence[Path], *, commands: Collection[str], caps: SkillCaps) -> list[Problem]:
    """Problems of every skill under `targets`; skills in a `roles` folder get the role
    rules, the others the installed-skill rules (SP4 spec decision 7)."""
    found: list[Problem] = []
    for path in _skill_files(targets):
        found += [Problem(str(path), m) for m in _lint_one(path, commands=commands, caps=caps)]
    return found


def mentions(body: str) -> list[list[str]]:
    """The words after `harness` in each command a skill shows: inline code spans, and
    fenced lines that start with `harness ` (or `$ harness `), up to the first flag,
    placeholder, quote or shell operator."""
    found: list[list[str]] = []
    fenced = False
    for line in body.splitlines():
        if line.strip().startswith(FENCE):
            fenced = not fenced
            continue
        texts = [line.strip().removeprefix("$ ")] if fenced else SPAN.findall(line)
        for text in texts:
            if text == "harness" or text.startswith("harness "):
                found.append(_command_words(text.split()[1:]))
    return found


def _command_words(words: list[str]) -> list[str]:
    kept: list[str] = []
    for word in words:
        if word.startswith(STOP):
            break
        kept.append(word)
    return kept


def _skill_files(targets: Sequence[Path]) -> Iterator[Path]:
    for target in targets:
        if target.is_file():
            yield target
        elif (target / "SKILL.md").is_file():
            yield target / "SKILL.md"
        elif target.is_dir():
            yield from sorted(
                child / "SKILL.md" for child in target.iterdir() if (child / "SKILL.md").is_file()
            )


def _lint_one(path: Path, *, commands: Collection[str], caps: SkillCaps) -> list[str]:
    text = path.read_text(encoding="utf-8")
    try:
        raw, body = split_frontmatter(text)
        meta = SkillMeta.model_validate(raw)
    except (UserError, ValidationError) as exc:
        return [f"frontmatter: {exc}".splitlines()[0]]
    folder = path.parent
    role = folder.parent.name == "roles"
    messages: list[str] = []
    if not re.fullmatch(NAME_PATTERN, meta.name) or len(meta.name) > NAME_MAX:
        messages.append(
            f"name must be lowercase words joined by single hyphens, at most {NAME_MAX} characters"
        )
    if meta.name != folder.name:
        messages.append(f"name {meta.name} does not match its folder {folder.name}")
    if not role:
        if not meta.description.startswith("Use when"):
            messages.append('description must start with "Use when"')
        if len(meta.description) > DESCRIPTION_MAX:
            messages.append(
                f"description has {len(meta.description)} characters; the cap is {DESCRIPTION_MAX}"
            )
    lines, words = len(text.splitlines()), len(text.split())
    if lines > caps.max_lines:
        messages.append(f"{lines} lines; the cap is {caps.max_lines}")
    if words > caps.max_words:
        messages.append(f"{words} words; the cap is {caps.max_words}")
    if not role and "harness --version" not in body:
        messages.append("step 0 must run harness --version")
    references = folder / "references"
    for name in dict.fromkeys(REFERENCE.findall(body)):
        if not (references / name).is_file():
            messages.append(f"references/{name} is missing")
    if references.is_dir() and any(child.is_dir() for child in references.iterdir()):
        messages.append("references/ must not hold folders")
    for words_ in mentions(body):
        unknown = _unknown(words_, commands)
        if unknown:
            messages.append(f"unknown command: harness {unknown}")
    return messages


def _unknown(words: list[str], commands: Collection[str]) -> str | None:
    """The command path that does not exist, or None."""
    if not words:
        return None
    first = words[0]
    if first not in commands:
        return first
    group = any(command.startswith(f"{first} ") for command in commands)
    if group and len(words) > 1 and f"{first} {words[1]}" not in commands:
        return f"{first} {words[1]}"
    return None
