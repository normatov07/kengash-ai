"""ticket changes and ticket attach (SP3 spec §10)."""

import shlex

import pytest
from conftest import Engine

from kengash_ai import gitops
from kengash_ai.model import SessionRef, UserError
from kengash_ai.ops import changes
from kengash_ai.ops.changes import Change
from kengash_ai.store import documents


def test_changes_list_files_with_their_loop_and_model(engine: Engine) -> None:
    (engine.worktree / "retry.py").write_text("a = 1\nb = 2\n")
    trailers = {
        "Harness-Ticket": str(engine.ticket().meta.uuid),
        "Harness-Step": "implement",
        "Harness-Loop": "1",
        "Harness-Agent": "implementer",
        "Harness-Model": "codex/default",
    }
    sha = gitops.commit_all(engine.worktree, "hrn(7b55e0c1): loop 1 implement: retry", trailers)
    assert sha is not None
    found = changes.ticket_changes("7b55e0c1", diff=True, project=None)
    assert found.ref == "kg/7b55e0c1"
    assert found.changes == [Change("retry.py", 2, 0, "1", "implement", "codex/default", sha)]
    assert "+b = 2" in found.diff


def test_attach_prints_the_resume_command(engine: Engine) -> None:
    doc = engine.ticket()
    doc.meta.sessions["planner"] = SessionRef(provider="claude", model="opus", id="s-1")
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    found = changes.attach_command("7b55e0c1", role=None, project=None)
    assert found.command == f"cd {shlex.quote(str(engine.worktree))} && claude --resume s-1"
    with pytest.raises(UserError, match="7b55e0c1 has no implementer session"):
        changes.attach_command("7b55e0c1", role="implementer", project=None)
