"""Skills (SP4 spec decisions 2 to 7): role skills for worker prompts; lint and install of
the installed skills, as the `kengash` plugin or `kengash-<name>` copies (SP10 spec §3)."""

import difflib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Collection, Iterator, Sequence
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
from kengash_ai.store.files import atomic_write
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
    """A role skill's file: a built-in skill always the package's, so it cannot be changed or
    go stale (SP10 spec §4.1); a user's skill the project's, else the defaults'."""
    if skill in ROLES:
        return roles_dir() / skill / "SKILL.md"
    folders = [paths.defaults / "roles"]
    if slug is not None:
        folders.insert(0, paths.project(slug).root / "roles")
    for folder in folders:
        path = folder / skill / "SKILL.md"
        if path.is_file():
            return path
    return None


type SkillSource = Literal["package", "defaults", "project"]


def role_skills(paths: StorePaths, slug: str | None) -> list[tuple[str, SkillSource]]:
    """Every role skill an agent of this scope can run, with where it lives: the package's
    built-in ones, then the user's in the defaults and the project."""
    found: dict[str, SkillSource] = dict.fromkeys(sorted(ROLES), "package")
    folders: list[tuple[Path, SkillSource]] = [(paths.defaults / "roles", "defaults")]
    if slug is not None:
        folders.append((paths.project(slug).root / "roles", "project"))
    for folder, source in folders:
        for child in sorted(folder.iterdir()) if folder.is_dir() else []:
            if child.name not in ROLES and (child / "SKILL.md").is_file():
                found[child.name] = source
    return list(found.items())


def ignored_copies(paths: StorePaths) -> list[Path]:
    """Store copies of built-in skills, which `role_file` never reads: the ones `kengash
    init` seeded before SP10, and any the user wrote by hand."""
    folders = [paths.defaults / "roles"]
    if paths.projects.is_dir():
        folders += [project / "roles" for project in sorted(paths.projects.iterdir())]
    return [
        folder / skill for folder in folders for skill in sorted(ROLES) if (folder / skill).is_dir()
    ]


def role_text(paths: StorePaths, slug: str, skill: str) -> str | None:
    """The body of a role skill, found by `role_file`."""
    path = role_file(paths, slug, skill)
    if path is None:
        return None
    try:
        return split_frontmatter(path.read_text(encoding="utf-8"))[1]
    except UserError:
        return path.read_text(encoding="utf-8")  # a hand-written file without frontmatter


HOOK_ARGS = "memory harvest --hook"
HOOK_EVENTS = ("PreCompact", "SessionEnd")
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


def show(name: str, *, agent: str, cli_name: str) -> str:
    """A packaged skill rendered as `install` renders it for `agent` (SP11 spec §3.1): the
    body without frontmatter, commands named `cli_name`, other skills spelled as `agent`
    types them, then each `references/<file>` as its own `## references/<file>` section,
    so one skill can hand over to the next whatever agent runs it."""
    source = packaged()
    known = sorted(path.name for path in source.iterdir() if (path / "SKILL.md").is_file())
    if name not in known:
        raise UserError(f"unknown skill: {name}; known: {', '.join(known)}")
    files = _render(source / name, cli_name, spelling_for(agent))
    _, body = split_frontmatter(files["SKILL.md"].decode("utf-8"))
    parts = [body.lstrip()]
    for path in sorted(files):
        if path.startswith("references/"):
            parts.append(f"\n## {path}\n\n{files[path].decode('utf-8', errors='replace')}")
    return "".join(parts)


def spelling_for(agent: str) -> str | None:
    """How `agent` types another kengash skill: Codex `$kengash-<name>`; claude and agy
    load the plugin, so None keeps `/kengash:<name>`."""
    return SPELLING["codex"] if agent == "codex" else None


def invoked_name(argv0: str) -> str:
    """The command skills should run to reach this CLI: `kengash` when it is the first
    `kengash` on PATH, else its full path (the rule `--cli-name` follows)."""
    if Path(argv0).name != CLI or os.sep not in argv0:
        return CLI  # `python -m`, a test runner, or a bare name found on PATH
    here = Path(argv0).resolve()
    found = shutil.which(CLI)
    return CLI if found is not None and Path(found).resolve() == here else str(here)


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
PLUGIN = "kengash"
AGY_PLUGINS = ".gemini/config/plugins"  # where `agy plugin install` copies a plugin
AGY_FAILED = "agy plugin install failed; copies instead"
TRUST_NOTE = (
    "Claude Code loads this project's plugin once you trust the folder; "
    "--global loads it everywhere"
)
# how a copy names a command: Codex mentions skills with `$`, Antigravity types `/`
SPELLING = {"codex": f"${PLUGIN}-", "antigravity": f"/{PLUGIN}-"}
# the names our skills had before SP10 (and 0.1.0's harness-memory), and who reads each folder
OLD_NAMES = frozenset(
    {"to-plan", "to-plan-with-grill", "to-ticket", "to-loop", "open-ui"}
    | {"kengash-memory", "harness-memory"}
)
READERS = {
    ".claude/skills": "claude",
    ".agents/skills": "codex,antigravity",
    ".gemini/config/skills": "antigravity",
}


def home_folder() -> Path:
    """The user's home folder: where global skills and agy's plugins live."""
    return Path.home()


def old_installs(roots: Sequence[Path]) -> list[tuple[Path, str]]:
    """Skill folders under `roots` that still hold our skills by their old names, each with
    the agents that read it."""
    found: list[tuple[Path, str]] = []
    for root in roots:
        for folder, agents in READERS.items():
            path = root / folder
            # kengash-memory is also the name of Codex's (and agy's fallback) current copy
            old = OLD_NAMES if folder == AGENT_DIRS["claude"] else OLD_NAMES - {"kengash-memory"}
            if any(stale.name in old for stale in _obsolete(path, ())):
                found.append((path, agents))
    return found


@dataclass
class Installed:
    agent: str
    name: str
    state: State
    folder: Path
    note: str = ""


@dataclass
class InstallResult:
    entries: list[Installed] = field(default_factory=list)
    diffs: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

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


def install_hooks(settings_path: Path, cli_name: str = CLI) -> str:
    """Merge the chat-capture hooks into a Claude Code settings file (SP18 spec §3.3); a note
    for the user, or "" when they were there already. An unreadable file is left alone."""
    try:
        text = settings_path.read_text(encoding="utf-8") if settings_path.exists() else "{}"
        data = json.loads(text)
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("hooks", {}), dict):
        return f"{settings_path} could not be read, so chat capture is not set up"
    hooks = data.setdefault("hooks", {})
    if not all(isinstance(hooks.get(event, []), list) for event in HOOK_EVENTS):
        return f"{settings_path} could not be read, so chat capture is not set up"
    added = False
    for event in HOOK_EVENTS:
        entries = hooks.setdefault(event, [])
        if HOOK_ARGS not in json.dumps(entries):
            command = f"{cli_name} {HOOK_ARGS}"
            entries.append({"hooks": [{"type": "command", "command": command, "timeout": 15}]})
            added = True
    if not added:
        return ""
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(settings_path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return f"chat capture: added {' and '.join(HOOK_EVENTS)} hooks to {settings_path}"


def plugin_manifest() -> dict[str, object]:
    """The `kengash` plugin's manifest, for Claude Code and Antigravity alike."""
    return {
        "name": PLUGIN,
        "author": {"name": "normatov13"},
        "version": kengash_ai.__version__,
        "description": "Plan, ticket and run many projects at once with the coding-agent "
        "subscriptions you already have, through the kengash CLI.",
        "homepage": "https://github.com/normatov07/kengash-ai",
        "license": "MIT",
    }


def install(
    agents: Sequence[str],
    *,
    root: Path,
    home: bool = False,
    cli_name: str = CLI,
    yes: bool = False,
    source: Path | None = None,
    agy_plugin: bool = True,
    user_home: Path | None = None,
    run: Callable[[list[str]], int] | None = None,
) -> InstallResult:
    """Install the skills for each agent under `root` (SP10 spec §3.2): Claude Code gets the
    plugin folder in its skills folder, Antigravity `agy plugin install` of the plugin (or
    copies when that fails or `agy_plugin` is off), Codex `kengash-<name>` copies. Old
    skills of ours go; a skill the user edited is replaced only with `yes`."""
    source = source or packaged()
    dirs = GLOBAL_DIRS if home else AGENT_DIRS
    names = sorted(child.name for child in source.iterdir() if (child / "SKILL.md").is_file())
    keep = {*names, *(f"{PLUGIN}-{name}" for name in names)}
    chosen: list[str] = []
    for agent in agents:
        name = ALIASES.get(agent.strip(), agent.strip())
        if name not in dirs:
            raise UserError(f"unknown agent {name}; use claude, codex or antigravity")
        if name not in chosen:
            chosen.append(name)
    result = InstallResult()
    copies: dict[Path, list[str]] = {}  # copy folder → its agents; Codex and agy may share one
    notes: dict[Path, str] = {}
    for agent in chosen:
        folder = root / dirs[agent]
        if agent == "claude":
            _clean(result, agent, folder, ())  # our skills live in the plugin folder now
            if not home:
                result.notes.append(TRUST_NOTE)
            elif note := install_hooks(root / ".claude" / "settings.json", cli_name):
                result.notes.append(note)  # chat capture is per user, never per repo
            plugin = folder / PLUGIN
            _write_manifest(plugin / ".claude-plugin" / "plugin.json")
            _clean(result, agent, plugin / "skills", names)
            for skill in names:
                files = _render(source / skill, cli_name)
                _place(result, agent, skill, plugin / "skills" / skill, files, yes)
            continue
        if agent == "antigravity" and agy_plugin:
            # a folder Codex shares keeps Codex's copies; agy's own loses every copy of ours
            _clean(result, agent, folder, keep if folder == root / dirs["codex"] else ())
            installed = (user_home or home_folder()) / AGY_PLUGINS / PLUGIN
            entry = _agy_plugin(source, names, cli_name, installed, run or _run)
            if entry is not None:
                result.entries.append(entry)
                continue
            notes[folder] = AGY_FAILED
        copies.setdefault(folder, []).append(agent)
    for folder, owners in copies.items():
        note = notes.get(folder, "")
        _copy_all(result, owners, folder, source, names, keep, cli_name, yes, note)
    return result


def _copy_all(
    result: InstallResult,
    owners: list[str],
    folder: Path,
    source: Path,
    names: list[str],
    keep: Collection[str],
    cli_name: str,
    yes: bool,
    note: str,
) -> None:
    """`kengash-<name>` copies of every skill in `folder`, spelled for an agent without a
    plugin namespace (Codex's `$` wins when Codex shares the folder)."""
    agent = ",".join(owners)
    spelling = SPELLING["codex" if "codex" in owners else "antigravity"]
    _clean(result, agent, folder, keep)
    for skill in names:
        files = _render(source / skill, cli_name, spelling)
        entry = _place(result, agent, skill, folder / f"{PLUGIN}-{skill}", files, yes)
        entry.note = note


def _agy_plugin(
    source: Path,
    names: list[str],
    cli_name: str,
    installed: Path,
    run: Callable[[list[str]], int],
) -> Installed | None:
    """Build the plugin in a temporary folder and `agy plugin install` it, unless agy
    already holds exactly these files; None when agy failed."""
    files = {
        f"skills/{skill}/{rel}": data
        for skill in names
        for rel, data in _render(source / skill, cli_name).items()
    }
    files[".antigravity-plugin/plugin.json"] = _manifest_bytes()
    name = f"{PLUGIN} (plugin)"
    if _files(installed) == files:
        return Installed("antigravity", name, "unchanged", installed)
    with tempfile.TemporaryDirectory(prefix="kengash-plugin-") as scratch:
        build = Path(scratch) / PLUGIN
        for rel, data in files.items():
            path = build / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        code = run(["agy", "plugin", "install", str(build)])
    return Installed("antigravity", name, "installed", installed) if code == 0 else None


def _place(
    result: InstallResult, agent: str, name: str, target: Path, files: dict[str, bytes], yes: bool
) -> Installed:
    installed = _files(target)
    state: State = "installed" if installed is None else "unchanged"
    if installed is not None and installed != files:
        state = "updated" if yes else "differs"
        if not yes:
            result.diffs[str(target)] = _diff(target, installed, files)
    if state in ("installed", "updated"):
        _swap(target, files)
    entry = Installed(agent, name, state, target)
    result.entries.append(entry)
    return entry


def _clean(result: InstallResult, agent: str, folder: Path, keep: Collection[str]) -> None:
    for stale in _obsolete(folder, keep):
        shutil.rmtree(stale)
        result.entries.append(Installed(agent, stale.name, "removed", stale))


def _manifest_bytes() -> bytes:
    return (json.dumps(plugin_manifest(), indent=2) + "\n").encode("utf-8")


def _write_manifest(path: Path) -> None:
    data = _manifest_bytes()
    if path.is_file() and path.read_bytes() == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _run(argv: list[str]) -> int:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)
    except FileNotFoundError:
        return 127
    except subprocess.TimeoutExpired:
        return 124
    return done.returncode


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


def _render(skill: Path, cli_name: str, spelling: str | None = None) -> dict[str, bytes]:
    """A skill's files with `kengash` swapped for `cli_name`; with `spelling`, a copy named
    `kengash-<name>` whose `/kengash:` commands read `<spelling><name>`."""
    files: dict[str, bytes] = {}
    for path in sorted(skill.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            if path.suffix == ".md":
                text = rename_cli(data.decode("utf-8"), cli_name)
                if spelling is not None:
                    text = text.replace(f"/{PLUGIN}:", spelling)
                    if path.name == "SKILL.md":
                        text = re.sub(
                            r"^name: (\S+)$", rf"name: {PLUGIN}-\1", text, count=1, flags=re.M
                        )
                data = text.encode("utf-8")
            files[path.relative_to(skill).as_posix()] = data
    return files


def _obsolete(folder: Path, keep: Collection[str]) -> list[Path]:
    """Skill folders this package installed once but ships no more (0.1.0's harness-memory,
    0.2.0's to-loop and the rest): only those whose frontmatter names us as
    `metadata.source`; anything else stays."""
    found: list[Path] = []
    for child in sorted(folder.iterdir()) if folder.is_dir() else []:
        path = child / "SKILL.md"
        if child.name in keep or not path.is_file():
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
