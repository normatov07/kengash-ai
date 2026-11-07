"""A ticket from ready to merged with a real detached worker and the fake CLIs (SP3 spec §11)."""

import time
from collections.abc import Callable

import pytest
from conftest import Engine, Events, FakeClis
from typer.testing import CliRunner

from kengash_ai.cli import app
from kengash_ai.store import documents, runtime

runner = CliRunner()
REVIEW_FAIL = {
    "verdict": "fail",
    "summary": "Missing jitter.",
    "findings": [
        {
            "severity": "medium",
            "file": "retry.py",
            "line": 3,
            "issue": "no jitter",
            "fix": "add jitter",
        }
    ],
}
REVIEW_PASS = {"verdict": "pass", "summary": "Good.", "findings": []}


@pytest.fixture
def lifecycle_repo(engine: Engine) -> Engine:
    """`engine` with its ticket back in the queue, as `kengash ticket add` leaves it."""
    doc = engine.ticket()
    doc.meta.status, doc.meta.step = "in_queue/ready", None
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    return engine


def queue_happy_path(fake_clis: FakeClis) -> None:
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"retry.py": "retries = 3\n"})
    fake_clis.queue("claude", stdout=fake_clis.claude_output(REVIEW_FAIL))
    fake_clis.queue(
        "codex", fixture="codex/work_resume.jsonl", edits={"retry.py": "retries = 3\njitter = 1\n"}
    )
    fake_clis.queue("claude", stdout=fake_clis.claude_output(REVIEW_PASS))


def wait_until(check: Callable[[], bool], within: float = 20.0) -> None:
    deadline = time.monotonic() + within
    while not check():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.1)


def test_a_ticket_goes_from_ready_to_merged(
    lifecycle_repo: Engine,
    fake_clis: FakeClis,
    run_git: Callable[..., str],
    journal_events: Events,
) -> None:
    queue_happy_path(fake_clis)
    assert (
        runner.invoke(app, ["run", "7b55e0c1"]).stdout
        == "started 7b55e0c1 plan→claude (watch: kengash logs 7b55e0c1 -f)\n"
    )
    waited = runner.invoke(app, ["wait", "--timeout", "60"])
    assert waited.exit_code == 0
    assert waited.stdout.startswith("7b55e0c1 in_process/awaiting_merge loop 2/3")
    merged = runner.invoke(app, ["merge", "7b55e0c1"])
    assert merged.stdout == "merged 7b55e0c1: 2 commits into main\n"
    worktree = lifecycle_repo.worktree.resolve()
    calls = [*fake_clis.calls("claude"), *fake_clis.calls("codex")]
    assert len(calls) == 5 and all(c["cwd"] == str(worktree) for c in calls)
    reviews = [c["argv"] for c in fake_clis.calls("claude")][1:]
    session = reviews[0][reviews[0].index("--session-id") + 1]
    stored = lifecycle_repo.ticket().meta.sessions["code-reviewer"].id
    assert reviews[1][reviews[1].index("--resume") + 1] == stored and session
    uuid = lifecycle_repo.ticket().meta.uuid
    grep = run_git(
        lifecycle_repo.repo, "log", "--format=%s", f"--grep=Kengash-Ticket: {uuid}", "main"
    )
    assert grep.splitlines() == [
        "kg(7b55e0c1): loop 2 implement: Added retry with backoff.",
        "kg(7b55e0c1): loop 1 implement: Added retry with backoff.",
    ]
    ends = [e for e in journal_events() if e["type"] == "step.end"]
    keys = {"provider", "model", "session", "tokens", "duration_s", "verdict"}
    assert len(ends) == 5 and all(keys <= e.keys() for e in ends)
    assert lifecycle_repo.ticket().meta.status == "done/merged"
    wait_until(lambda: runtime.load_workers(lifecycle_repo.paths) == [])
