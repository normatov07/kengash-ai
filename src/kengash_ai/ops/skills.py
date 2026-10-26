"""Skills (SP4 spec decisions 2 to 7): role skills for worker prompts; lint and install of
the installed skills."""

import difflib
import os
import re
import shutil
from collections.abc import Collection, Iterator, Sequence
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

import kengash_ai
from kengash_ai import settings
from kengash_ai.model import KengashError, SkillMeta, UserError
from kengash_ai.model.settings import SkillCaps
from kengash_ai.model.skills import DESCRIPTION_MAX, NAME_MAX, NAME_PATTERN
from kengash_ai.ops import records
from kengash_ai.store.frontmatter import split_frontmatter
from kengash_ai.store.paths import StorePaths

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
    """The package's role skills, `kengash_ai/roles/<role>/SKILL.md`."""
    return Path(str(resources.files("kengash_ai") / "roles"))


def role_file(paths: StorePaths, slug: str | None, skill: str) -> Path | None:
    """A role skill's file: the project's, else the defaults', else the package's."""
    folders = [paths.defaults / "roles", roles_dir()]
    if slug is not None:
        folders.insert(0, paths.project(slug).root / "roles")
    for folder in folders:
        path = folder / skill / "SKILL.md"
        if path.is_file():
            return path
    return None


def role_text(paths: StorePaths, slug: str, skill: str) -> str | None:
    """The body of a role skill: the project's, else the defaults', else the package's."""
    path = role_file(paths, slug, skill)
    if path is None:
        return None
    try:
        return split_frontmatter(path.read_text(encoding="utf-8"))[1]
    except UserError:
        return path.read_text(encoding="utf-8")  # a hand-written file without frontmatter


AGENT_DIRS = {
    "claude": ".claude/skills",
    "codex": ".agents/skills",
    "antigravity": ".agents/skills",
}
GLOBAL_DIRS = {
    "claude": ".claude/skills",
    "codex": ".agents/skills",
    "antigravity": ".gemini/config/skills",
}
ALIASES = {"agy": "antigravity"}
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
    inside = Path(str(resources.files("kengash_ai") / "skills"))
    if inside.is_dir():
        return inside
    return Path(kengash_ai.__file__).resolve().parents[2] / "skills"


def lint_skills(targets: Sequence[Path], *, commands: Collection[str]) -> list[Problem]:
    """`kengash skills lint`: the given targets, else the installed and role skills, with
    the user's `skill.*` caps (the package's when there is no store)."""
    try:
        caps = settings.load(StorePaths.default()).skill
    except KengashError:
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
    """The words after `kengash` in each command a skill shows: inline code spans, and
    fenced lines that start with `kengash ` (or `$ kengash `), up to the first flag,
    placeholder, quote or shell operator."""
    found: list[list[str]] = []
    fenced = False
    for line in body.splitlines():
        if line.strip().startswith(FENCE):
            fenced = not fenced
            continue
        texts = [line.strip().removeprefix("$ ")] if fenced else SPAN.findall(line)
        for text in texts:
            if text == CLI or text.startswith(f"{CLI} "):
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
    if not role and f"{CLI} --version" not in body:
        messages.append(f"step 0 must run {CLI} --version")
    references = folder / "references"
    for name in dict.fromkeys(REFERENCE.findall(body)):
        if not (references / name).is_file():
            messages.append(f"references/{name} is missing")
    if references.is_dir() and any(child.is_dir() for child in references.iterdir()):
        messages.append("references/ must not hold folders")
    for words_ in mentions(body):
        unknown = _unknown(words_, commands)
        if unknown:
            messages.append(f"unknown command: {CLI} {unknown}")
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


State = Literal["installed", "updated", "unchanged", "differs", "removed"]
CLI = "kengash"  # the command skills run; `--cli-name` swaps it at install time
# frontmatter `metadata.source` of the skills this package installs, now and before 0.2.0
OURS = frozenset({"kengash-ai", "super-harness"})


@dataclass
class Installed:
    agent: str
    name: str
    state: State
    folder: Path


@dataclass
class InstallResult:
    entries: list[Installed] = field(default_factory=list)
    diffs: dict[str, str] = field(default_factory=dict)

    @property
    def needs_yes(self) -> bool:
        """Some installed skill differs from the package and was left alone."""
        return any(entry.state == "differs" for entry in self.entries)


def install_skills(
    agents: Sequence[str], *, global_: bool, path: Path, cli_name: str, yes: bool
) -> InstallResult:
    """`kengash skills install`: into the repo containing `path`, or the home folder."""
    root = Path.home() if global_ else records.repo_root(path)
    return install(agents, root=root, home=global_, cli_name=cli_name, yes=yes)


def install(
    agents: Sequence[str],
    *,
    root: Path,
    home: bool = False,
    cli_name: str = CLI,
    yes: bool = False,
    source: Path | None = None,
) -> InstallResult:
    """Copy every installed skill into each agent's skills folder under `root` (SP4 spec
    decisions 4 to 6); a skill that differs is replaced only with `yes`."""
    source = source or packaged()
    dirs = GLOBAL_DIRS if home else AGENT_DIRS
    folders: dict[Path, list[str]] = {}
    for agent in agents:
        name = ALIASES.get(agent.strip(), agent.strip())
        if name not in dirs:
            raise UserError(f"unknown agent {name}; use claude, codex or antigravity")
        owners = folders.setdefault(root / dirs[name], [])
        if name not in owners:
            owners.append(name)
    result = InstallResult()
    packaged_names = {child.name for child in source.iterdir() if (child / "SKILL.md").is_file()}
    for folder, owners in folders.items():
        for stale in _obsolete(folder, packaged_names):
            shutil.rmtree(stale)
            result.entries.append(Installed(",".join(owners), stale.name, "removed", stale))
        for skill in sorted(child for child in source.iterdir() if (child / "SKILL.md").is_file()):
            files = _render(skill, cli_name)
            target = folder / skill.name
            installed = _files(target)
            state: State = "installed" if installed is None else "unchanged"
            if installed is not None and installed != files:
                state = "updated" if yes else "differs"
                if not yes:
                    result.diffs[str(target)] = _diff(target, installed, files)
            if state in ("installed", "updated"):
                _swap(target, files)
            result.entries.append(Installed(",".join(owners), skill.name, state, target))
    return result


def rename_cli(text: str, name: str) -> str:
    """`text` with `kengash` replaced by `name` where it starts a command: in code spans
    and at the start of fenced lines; prose keeps the word."""
    if name == CLI:
        return text
    lines: list[str] = []
    fenced = False
    for line in text.splitlines(keepends=True):
        if line.strip().startswith(FENCE):
            fenced = not fenced
        elif fenced:
            line = re.sub(rf"^(\s*(?:\$ )?){CLI}(?= |$)", rf"\g<1>{name}", line)
        else:
            line = re.sub(rf"`{CLI}(?=[ `])", f"`{name}", line)
        lines.append(line)
    return "".join(lines)


def _render(skill: Path, cli_name: str) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in sorted(skill.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            if path.suffix == ".md":
                data = rename_cli(data.decode("utf-8"), cli_name).encode("utf-8")
            files[path.relative_to(skill).as_posix()] = data
    return files


def _obsolete(folder: Path, packaged: Collection[str]) -> list[Path]:
    """Skill folders this package installed once but ships no more (0.1.0's harness-memory):
    only those whose frontmatter names us as `metadata.source`; anything else stays."""
    found: list[Path] = []
    for child in sorted(folder.iterdir()) if folder.is_dir() else []:
        path = child / "SKILL.md"
        if child.name in packaged or not path.is_file():
            continue
        try:
            meta = SkillMeta.model_validate(split_frontmatter(path.read_text(encoding="utf-8"))[0])
        except (UserError, ValidationError):
            continue
        if meta.metadata.get("source") in OURS:
            found.append(child)
    return found


def _files(folder: Path) -> dict[str, bytes] | None:
    if not folder.is_dir():
        return None
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def _diff(target: Path, installed: dict[str, bytes], files: dict[str, bytes]) -> str:
    parts: list[str] = []
    for name in sorted(set(installed) | set(files)):
        old = installed.get(name, b"").decode("utf-8", "replace").splitlines(keepends=True)
        new = files.get(name, b"").decode("utf-8", "replace").splitlines(keepends=True)
        parts += difflib.unified_diff(
            old, new, fromfile=f"{target / name} (installed)", tofile=f"{name} (kengash_ai)"
        )
    return "".join(parts)


def _swap(target: Path, files: dict[str, bytes]) -> None:
    """Write the skill beside `target`, then swap it in, so a reader never sees half of it."""
    fresh = target.parent / f".{target.name}.new-{os.getpid()}"
    shutil.rmtree(fresh, ignore_errors=True)
    for name, data in files.items():
        path = fresh / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    if target.exists():
        old = target.parent / f".{target.name}.old-{os.getpid()}"
        target.rename(old)
        fresh.rename(target)
        shutil.rmtree(old)
    else:
        fresh.rename(target)
