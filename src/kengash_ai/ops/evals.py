"""Skill evals (SP4 spec decisions 11 to 13): scenarios replayed headless against a
temporary store and scratch repo, on each agent, with their expectations checked."""

import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

import kengash_ai
from kengash_ai import journal
from kengash_ai.adapters.base import positional
from kengash_ai.adapters.env import worker_env
from kengash_ai.adapters.process import run_process
from kengash_ai.model import EvalScenario, Expect, NeedsSetup, RecordsExpect, UserError
from kengash_ai.ops import agents, lifecycle, records, skills
from kengash_ai.store import runtime
from kengash_ai.store.paths import StorePaths
from kengash_ai.store.registry import load_registry
from kengash_ai.store.yamlio import load_yaml

EVALS_DIR = Path(kengash_ai.__file__).resolve().parents[2] / "evals"
PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")
HEX8 = re.compile(r"\b[0-9a-f]{8}\b")
CHEAPEST: dict[str, str | None] = {
    "claude": "haiku",
    "codex": None,
    "antigravity": "gemini-3.8-flash-low",
}
CLAUDE_TOOLS = ("Read", "Grep", "Glob", "Bash(harness:*)")
BIN = Path(sys.executable).parent  # this interpreter's console scripts, harness among them
TAIL = 400


AGENTS = ("claude", "codex", "antigravity")


@dataclass
class EvalRun:
    name: str
    agent: str
    passed: bool
    failure: str
    work: Path


def load(path: Path) -> EvalScenario:
    """One scenario file; a problem names the file."""
    try:
        return EvalScenario.model_validate(load_yaml(path.read_text(encoding="utf-8"), path.name))
    except ValidationError as exc:
        raise UserError(f"{path.name}: {records.describe(exc)}") from exc


def scenarios(root: Path, skill: str | None) -> list[tuple[str, Path]]:
    """`(<skill>/<scenario>, path)` for one skill's scenarios, or every skill's."""
    pattern = f"{skill}/*.yaml" if skill else "*/*.yaml"
    found = sorted(root.glob(pattern))
    if not found:
        raise UserError(f"no eval scenarios for {skill or 'any skill'} in {root}")
    return [(f"{path.parent.name}/{path.stem}", path) for path in found]


def fill(text: str, values: Mapping[str, str]) -> str:
    """`text` with each `{name}` that `values` knows replaced."""
    return PLACEHOLDER.sub(lambda match: values.get(match.group(1), match.group(0)), text)


def run_evals(
    skill: str | None,
    *,
    agents_: Sequence[str] | None,
    model: str | None,
    baseline: bool,
    root: Path = EVALS_DIR,
    keep: Path | None = None,
) -> tuple[list[EvalRun], Path]:
    """Every scenario of `skill` (or of every skill) on each agent; the runs and the
    folder that holds their transcripts."""
    named = scenarios(root, skill)
    chosen = _agents(agents_)
    base = keep or Path(tempfile.mkdtemp(prefix="harness-eval-"))
    runs: list[EvalRun] = []
    for name, path in named:
        scenario = load(path)
        for agent in chosen:
            work = base / f"{name.replace('/', '-')}-{agent}"
            used = model or CHEAPEST[agent]
            runs.append(
                run_scenario(name, scenario, agent, work=work, model=used, baseline=baseline)
            )
    return runs, base


def _agents(named: Sequence[str] | None) -> list[str]:
    """The named agents, each installed and signed in; by default every usable one."""
    with tempfile.TemporaryDirectory() as scratch:
        detect = agents.detector(StorePaths(Path(scratch)))
        if named is None:
            usable = [agent for agent in AGENTS if detect(agent).usable]
            if not usable:
                raise NeedsSetup("no agent CLI is installed and signed in")
            return usable
        chosen: list[str] = []
        for raw in named:
            agent = skills.ALIASES.get(raw.strip(), raw.strip())
            if agent not in AGENTS:
                raise UserError(f"unknown agent {agent}; use claude, codex or antigravity")
            problem = agents.problem(agent, detect)
            if problem is not None:
                raise NeedsSetup(problem)
            chosen.append(agent)
        return chosen


def agent_values(agent: str, model: str | None) -> dict[str, str]:
    """`{agent}`, `{model}` and `{cli}` (`<agent>/<model>`, or the agent alone), so a
    scenario can put workers and reviewers on the conductor's own CLI and model."""
    return {"agent": agent, "model": model or "", "cli": f"{agent}/{model}" if model else agent}


def conductor_argv(agent: str, turn: str, *, model: str | None, session: str | None) -> list[str]:
    """One headless conductor turn (SP4 spec §5): a new session, or `session` resumed."""
    text = positional(turn)
    if agent == "claude":
        argv = ["claude", "-p", text, "--output-format", "json"]
        argv += ["--resume", session] if session else []
        argv += ["--model", model] if model else []
        argv += ["--setting-sources", "project,local", "--strict-mcp-config"]
        return [*argv, "--permission-mode", "dontAsk", "--allowedTools", *CLAUDE_TOOLS]
    if agent == "antigravity":
        argv = ["agy", "-p", text, "--output-format", "json"]
        argv += ["--conversation", session] if session else []
        argv += ["--model", model] if model else []
        return [*argv, "--dangerously-skip-permissions", "--sandbox"]
    if agent == "codex":
        flags = ["--json", "--ignore-user-config", "--dangerously-bypass-approvals-and-sandbox"]
        flags += ["-m", model] if model else []
        if session:
            return ["codex", "exec", "resume", *flags, session, text]
        return ["codex", "exec", *flags, text]
    raise UserError(f"unknown agent {agent}; use claude, codex or antigravity")


def parse_turn(agent: str, stdout: str) -> tuple[str | None, str]:
    """The session id and the reply text of one turn's output."""
    if agent == "codex":
        session, reply = None, ""
        for line in stdout.splitlines():
            with contextlib.suppress(ValueError):
                event = json.loads(line)
                if event.get("type") == "thread.started":
                    session = event.get("thread_id")
                item = event.get("item") or {}
                if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                    reply = str(item.get("text", ""))
        return session, reply
    try:
        data = json.loads(stdout)
    except ValueError:
        return None, stdout.strip()[-TAIL:]
    if agent == "claude":
        return data.get("session_id"), str(data.get("result") or "")
    return data.get("conversation_id"), str(data.get("response") or "")


def run_scenario(
    name: str,
    scenario: EvalScenario,
    agent: str,
    *,
    work: Path,
    model: str | None,
    baseline: bool = False,
    source: Path | None = None,
) -> EvalRun:
    """Build the sandbox, run every turn headless, stop leftover workers, check."""
    home, repo = work / "home" / ".harness", work / "repo"
    paths = StorePaths(home)
    env = _env(agent, home, work)

    def failed(reason: str) -> EvalRun:
        return EvalRun(name, agent, False, reason, work)

    _scratch_repo(repo, scenario.files, env)
    values = agent_values(agent, model)
    init = _harness(["init", str(repo)], env, repo)
    if init.returncode != 0:
        return failed(f"harness init failed: {_tail(init.stderr)}")
    slug = next(iter(load_registry(paths).projects))
    if scenario.settings:
        for target in (paths.defaults / "SETTINGS.md", paths.project(slug).settings):
            target.write_text(fill(scenario.settings, values), encoding="utf-8")
    for number, step in enumerate(scenario.setup, 1):
        args = [fill(arg, values) for arg in step.args]
        done = _harness(args, env, repo, stdin=fill(step.stdin, values))
        if done.returncode != 0:
            return failed(f"setup step {number} failed: {_tail(done.stderr or done.stdout)}")
        if step.save:
            found = HEX8.search(done.stdout)
            if found is None:
                return failed(f"setup step {number} printed no id to save")
            values[step.save] = found.group(0)
    if not baseline:
        skills.install([agent], root=repo, source=source)
    try:
        return _turns(name, scenario, agent, work, model, values, paths, slug, repo, env)
    finally:
        _stop_ui(paths)  # a UI the conductor started never outlives the run


def _turns(
    name: str,
    scenario: EvalScenario,
    agent: str,
    work: Path,
    model: str | None,
    values: dict[str, str],
    paths: StorePaths,
    slug: str,
    repo: Path,
    env: dict[str, str],
) -> EvalRun:
    def failed(reason: str) -> EvalRun:
        return EvalRun(name, agent, False, reason, work)

    session: str | None = None
    reply = ""
    before = _changes(repo)  # installed skills are the runner's, not the conductor's
    try:
        for number, turn in enumerate(scenario.turns, 1):
            argv = conductor_argv(agent, fill(turn, values), model=model, session=session)
            log = work / f"turn-{number}.out"
            result = run_process(argv, cwd=repo, env=env, timeout_s=scenario.timeout_s, log=log)
            if result.timed_out:
                return failed(f"turn {number} timed out after {scenario.timeout_s} s")
            if result.exit_code != 0:
                return failed(f"turn {number} exit {result.exit_code}: {_tail(result.stderr)}")
            found_session, reply = parse_turn(agent, result.stdout)
            session = found_session or session
    finally:
        _stop_workers(paths)
    problem = check(scenario.expect, paths, slug, values, reply)
    if problem is None and scenario.expect.clean:
        changed = sorted(_changes(repo) - before)
        problem = f"the repo has changes: {', '.join(changed)}" if changed else None
    return EvalRun(name, agent, problem is None, problem or "", work)


def check(
    expect: Expect, paths: StorePaths, slug: str, values: Mapping[str, str], reply: str
) -> str | None:
    """The first expectation the store, the journal or the reply misses, or None."""
    types = {event.type for event in journal.read(paths)} if paths.journal.is_dir() else set()
    for kind in expect.journal:
        if kind not in types:
            return f"journal has no {kind}"
    for kind in expect.absent:
        if kind in types:
            return f"journal has {kind}"
    plans = [
        doc.meta.model_dump(mode="json") for doc in records.project_plans(paths, slug).values()
    ]
    tickets = [
        doc.meta.model_dump(mode="json") for doc in records.project_tickets(paths, slug).values()
    ]
    for noun, wanted, found in (("plan", expect.plans, plans), ("ticket", expect.tickets, tickets)):
        problem = _records(noun, wanted, found, values)
        if problem:
            return problem
    for file, texts in (("MEMORY.md", expect.memory), ("DECISIONS.md", expect.decisions)):
        content = (paths.memory / file).read_text(encoding="utf-8") if texts else ""
        for text in texts:
            if fill(text, values) not in content:
                return f'{file} lacks "{text}"'
    if expect.ui:
        record = runtime.load_ui(paths)
        if record is None or not lifecycle.pid_alive(record.pid):
            return "the UI server is not running"
    for text in expect.reply:
        if fill(text, values) not in reply:
            return f'the reply lacks "{text}"'
    return None


def _records(
    noun: str, wanted: RecordsExpect | None, found: list[dict[str, Any]], values: Mapping[str, str]
) -> str | None:
    if wanted is None:
        return None
    if wanted.count is not None and len(found) != wanted.count:
        return f"{noun}s: {len(found)}, expected {wanted.count}"
    if wanted.min is not None and len(found) < wanted.min:
        return f"{noun}s: {len(found)}, expected at least {wanted.min}"
    for record in found:
        for field, expected in wanted.fields.items():
            actual = _dotted(record, field)
            if actual != fill(expected, values):
                return (
                    f"{noun} {record['id']}: {field} is {actual}, expected {fill(expected, values)}"
                )
    return None


def _dotted(record: Mapping[str, Any], field: str) -> str:
    value: Any = record
    for part in field.split("."):
        value = value.get(part) if isinstance(value, Mapping) else None
    return "" if value is None else str(value)


def _env(agent: str, home: Path, work: Path) -> dict[str, str]:
    """The conductor's environment: no API keys or conductor markers, its own store and
    git identity, and this interpreter's `harness` first on PATH."""
    work.mkdir(parents=True, exist_ok=True)
    config = work / "gitconfig"
    config.write_text("[user]\n\tname = Eval\n\temail = eval@example.com\n", encoding="utf-8")
    env = worker_env(os.environ, agent, agent, allow_api_key=False)
    env |= {"HARNESS_HOME": str(home), "GIT_CONFIG_GLOBAL": str(config), "GIT_CONFIG_NOSYSTEM": "1"}
    env["PATH"] = os.pathsep.join([str(BIN), env.get("PATH", "")])
    env["BROWSER"] = "true"  # `harness ui open` opens no window on the user's desktop
    return env


def _scratch_repo(repo: Path, files: Mapping[str, str], env: Mapping[str, str]) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    for name, text in {"README.md": "scratch\n", **files}.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "scratch"]):
        subprocess.run(["git", *args], cwd=repo, env=dict(env), check=True, capture_output=True)


def _harness(
    args: list[str], env: Mapping[str, str], cwd: Path, *, stdin: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(BIN / "harness"), *args],
        cwd=cwd,
        env=dict(env),
        input=stdin,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def _changes(repo: Path) -> set[str]:
    """Paths `git status` reports in the scratch repo (its store link is excluded)."""
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    return {line[3:] for line in status.stdout.splitlines() if line.strip()}


def _stop_ui(paths: StorePaths) -> None:
    """End the sandbox store's UI server, if the conductor started one."""
    record = runtime.load_ui(paths)
    if record is None:
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(record.pid, signal.SIGTERM)
    for _ in range(50):
        if not lifecycle.pid_alive(record.pid):
            break
        time.sleep(0.05)
    runtime.drop_ui(paths)


def _stop_workers(paths: StorePaths) -> None:
    """End the process group of every worker the conductor left running."""
    for record in runtime.load_workers(paths):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(record.pid, signal.SIGTERM)


def _tail(text: str) -> str:
    return " ".join(text.strip().splitlines()[-3:])[-TAIL:]
