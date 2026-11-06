"""Live smoke (SP3 spec §11, decision 35): the real provider CLIs on a scratch repo.

Opt in with `uv run pytest -m live` (or `make live`); `make check` never runs these. A
provider that is not installed or not signed in is skipped. Every agent, the plan
reviewer and the compactor run on the provider's cheapest model.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest
from conftest import git, write_settings
from typer.testing import CliRunner

from kengash_ai import adapters
from kengash_ai.cli import app
from kengash_ai.model import Doc, Plan, Ticket
from kengash_ai.ops import evals, projects, records
from kengash_ai.store import StorePaths, runtime

pytestmark = [pytest.mark.live, pytest.mark.timeout(0)]  # real CLIs take minutes
runner = CliRunner()
PROVIDERS = ("claude", "codex", "antigravity")
CHEAPEST = {"claude": "haiku", "codex": None, "antigravity": "gemini-3.8-flash-low"}
ROLES = {
    "planner": "plan",
    "plan-reviewer": "review-plan",
    "implementer": "implement",
    "code-reviewer": "review-code",
    "security-reviewer": "review-security",
}
TEST_CMD = "python3 -c 'import calc; assert calc.add(2, 3) == 5'"
PINS = ("- ships small, reviews hard (pin)", "- never push to main without asking (pin)")
MEMORY = [
    "# MEMORY.md",
    "",
    "Global memory, read at the start of every command.",
    "",
    "## Working style",
    "",
    PINS[0],
    "- ships small changes",
    "- prefers small pull requests",
    "- likes small diffs",
    "- keeps changes small",
    "- reviews every diff closely",
    "- reviews diffs hard",
    "",
    "## Goals",
    "",
    "- payments service first",
    "- the payments service comes first",
    "- payments are the first goal",
    "- then the reporting dashboard",
    "- reporting dashboard after payments",
    "",
    "## Preferences",
    "",
    PINS[1],
    "- wants the diff, not prose",
    "- prefers diffs over prose",
    "- likes terse answers",
    "- terse replies please",
    "",
    "## Turned down",
    "",
    "- a second database",
]


@pytest.fixture
def fake_clis() -> None:
    """Replaces the autouse fakes: live tests run the real CLIs on the real PATH."""


@pytest.fixture(params=PROVIDERS)
def provider(request: pytest.FixtureRequest, tmp_path: Path) -> str:
    name = str(request.param)
    status = adapters.get(name, runtime=tmp_path / "runtime").detect()
    if not status.usable:
        pytest.skip(f"{name} is {'signed out' if status.installed else 'not installed'}")
    return name


def cli_of(provider: str) -> str:
    model = os.environ.get(f"KENGASH_LIVE_{provider.upper()}_MODEL", CHEAPEST[provider])
    return f"{provider}/{model}" if model else provider


@pytest.fixture
def scratch(
    provider: str, store_paths: StorePaths, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """A registered scratch repo whose every agent runs on `provider`'s cheapest model."""
    config = tmp_path / "gitconfig"
    config.write_text("[user]\n\tname = Live\n\temail = live@example.com\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.delenv("KENGASH_AGENT", raising=False)
    monkeypatch.delenv("HARNESS_AGENT", raising=False)
    repo = tmp_path / "calc"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "calc.py").write_text(
        '"""Small arithmetic helpers."""\n\n\ndef sub(a: int, b: int) -> int:\n    return a - b\n',
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "init")
    projects.init_project(repo)
    cli = cli_of(provider)
    agents = "".join(
        f"  {role}: {{cli: {cli}, skill: {skill}, fallback: []}}\n" for role, skill in ROLES.items()
    )
    write_settings(
        store_paths,
        f"merge.mode: ask\nstep_timeout_min: 10\nplan.reviewer: {cli}\n"
        f"memory.compactor: {cli}\nmemory.compact_at_lines: 24\n"
        f"project.test_cmd: {json.dumps(TEST_CMD)}\nagents:\n{agents}",
        slugs=(None, "calc"),
    )
    monkeypatch.chdir(repo)
    return repo


def ticket(paths: StorePaths, ticket_id: str) -> Doc[Ticket]:
    _, path = records.locate_ticket(paths, ticket_id, None)
    return records.load_ticket(path)


def plan(paths: StorePaths, plan_id: str) -> Doc[Plan]:
    _, path = records.locate_plan(paths, plan_id, None)
    return records.load_plan(path)


def journal(paths: StorePaths) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for day in sorted(paths.journal.glob("*.jsonl"))
        for line in day.read_text(encoding="utf-8").splitlines()
    ]


def test_a_ticket_runs_end_to_end(scratch: Path, store_paths: StorePaths, provider: str) -> None:
    made = runner.invoke(
        app,
        ["plan", "new", "--title", "Add add()", "--mode", "quick"],
        input="Add an add(a, b) function to calc.py.\n",
    )
    plan_id = made.stdout.split()[1]
    batch = [
        {
            "title": "Add add(a, b) to calc.py",
            "importance": "simple",
            "touches": ["calc.py"],
            "scope": "Add add(a: int, b: int) -> int to calc.py; it returns a + b.",
            "acceptance": ["calc.add(2, 3) == 5"],
        }
    ]
    added = runner.invoke(app, ["ticket", "add", "--plan", plan_id], input=json.dumps(batch))
    assert added.exit_code == 0, added.output
    ticket_id = added.stdout.split(": ")[1].split()[0]
    started = runner.invoke(app, ["run", ticket_id])
    assert started.stdout.startswith(f"started {ticket_id} plan→{provider}"), started.output
    waited = runner.invoke(app, ["wait", "--timeout", "1800"])
    doc = ticket(store_paths, ticket_id)
    log = (store_paths.logs / f"{ticket_id}.log").read_text(encoding="utf-8")[-3000:]
    assert doc.meta.status == "in_process/awaiting_merge", (
        f"{waited.output}\n{doc.sections.get('Log')}\n{doc.sections.get('Findings')}\n{log}"
    )
    merged = runner.invoke(app, ["merge", ticket_id])
    assert merged.exit_code == 0, merged.output
    check = subprocess.run(
        ["python3", "-c", "import calc; print(calc.add(2, 3))"],
        cwd=scratch,
        capture_output=True,
        text=True,
    )
    assert check.stdout == "5\n", check.stderr
    found = git(scratch, "log", "--format=%H", f"--grep=Kengash-Ticket: {doc.meta.uuid}", "main")
    assert found.strip()
    assert {"planner", "implementer", "code-reviewer"} <= set(doc.meta.sessions)
    ends = [e for e in journal(store_paths) if e["type"] == "step.end"]
    assert len(ends) >= 3
    for end in ends:
        tokens = end["tokens"]
        assert isinstance(tokens, dict) and tokens["in"] + tokens["out"] > 0, end


def test_a_plan_review_round(scratch: Path, store_paths: StorePaths) -> None:
    made = runner.invoke(
        app,
        ["plan", "new", "--title", "Add add()", "--mode", "direct"],
        input="Add an add(a, b) function to calc.py.\n",
    )
    plan_id = made.stdout.split()[1]
    sections = (
        "## Goal\ncalc.py gains add(a, b), returning a + b.\n"
        "## Scope\nOne function in calc.py.\n"
        "## Design\n`def add(a: int, b: int) -> int: return a + b`, beside sub().\n"
        "## Acceptance\n- [ ] calc.add(2, 3) == 5\n"
    )
    runner.invoke(app, ["plan", "save", plan_id], input=sections)
    result = runner.invoke(app, ["plan", "review", plan_id, "--timeout", "900", "--by", "user"])
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith(f"plan {plan_id} round 1: ")
    review = plan(store_paths, plan_id)
    assert review.meta.review.round == 1 and review.meta.review.session is not None
    lines = review.sections["Review log"].splitlines()
    assert lines and all(line.startswith("- round 1 · ") for line in lines)


def test_memory_compaction(scratch: Path, store_paths: StorePaths) -> None:
    path = store_paths.memory / "MEMORY.md"
    path.write_text("\n".join(MEMORY) + "\n", encoding="utf-8")
    result = runner.invoke(app, ["memory", "compact", "--timeout", "900"])
    assert result.exit_code == 0, result.output
    text = path.read_text(encoding="utf-8")
    assert all(pin in text.splitlines() for pin in PINS), text
    assert len(text.splitlines()) < 24, text


def test_a_conductor_keeps_one_lease_pid(
    provider: str, store_paths: StorePaths, tmp_path: Path
) -> None:
    """SP11 spec §9: every `kengash` call of one agent session finds the same conductor
    pid, so the session's own `wait` never looks like another loop."""
    turn = (
        "Run exactly these two shell commands, each as its own tool call, then reply DONE: "
        "`kengash loop claim`, then `kengash loop status --json`."
    )
    argv = evals.conductor_argv(provider, turn, model=CHEAPEST[provider], session=None)
    env = evals._env(provider, store_paths.home, tmp_path / "work")
    subprocess.run(argv, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=600)
    (lease,) = runtime.load_leases(store_paths)
    assert lease.project is None and lease.command in ("claude", "codex", "agy")
    loops = [
        text
        for day in store_paths.journal.glob("*.jsonl")
        for text in day.read_text(encoding="utf-8").splitlines()
        if '"loop.' in text
    ]
    assert len(loops) == 1 and '"loop.started"' in loops[0]  # one claim, no second lease
