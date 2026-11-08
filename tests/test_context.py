"""Exact context, marked for freshness (SP17 spec §3.8)."""

import hashlib
import os
from pathlib import Path

import pytest
from conftest import Engine, FakeClis

from kengash_ai import gitops, memory
from kengash_ai.ops import context, prompts, steps
from kengash_ai.store import StorePaths, documents, runtime


def _pack(root: Path, files: list[str], budget: int = 50_000, shared: tuple[str, ...] = ()) -> str:
    return context.file_pack(root, files, commit="abc1234", shared=shared, budget=budget)


def test_a_file_comes_with_its_exact_contents_and_blob(tmp_path: Path) -> None:
    body = "x = 1\ny = 2\n"
    (tmp_path / "a.py").write_text(body)
    blob = hashlib.sha1(f"blob {len(body)}\0{body}".encode()).hexdigest()[:10]  # noqa: S324
    text = _pack(tmp_path, ["a.py"])
    assert f"### a.py · 2 lines · blob {blob}" in text
    assert body in text
    assert "abc1234" in text


def test_a_fence_outgrows_the_file(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("```\ncode\n```\n")
    assert "````" in _pack(tmp_path, ["a.md"])


def test_a_missing_path_is_named_as_new_or_mistaken(tmp_path: Path) -> None:
    text = _pack(tmp_path, ["ghost.py"])
    assert "new or mistaken" in text and "ghost.py" in text


def test_binary_huge_and_shared_files_stay_out_but_are_named(tmp_path: Path) -> None:
    (tmp_path / "b.png").write_bytes(b"\x89PNG\0\0")
    (tmp_path / "huge.py").write_text("x" * (context.MAX_FILE_BYTES + 1))
    (tmp_path / "a.g.dart").write_text("generated\n")
    text = _pack(tmp_path, ["b.png", "huge.py", "a.g.dart"], shared=("*.g.dart",))
    for name in ("b.png", "huge.py", "a.g.dart"):
        assert name in text
    assert "generated\n" not in text and "xxxx" not in text


def test_a_path_outside_the_worktree_is_never_read(tmp_path: Path) -> None:
    root = tmp_path / "work"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("hunter2\n")
    (root / "link.txt").symlink_to(tmp_path / "secret.txt")
    text = _pack(root, ["../secret.txt", "link.txt", "/etc/hostname"])
    assert "hunter2" not in text


def test_a_directory_is_not_read(tmp_path: Path) -> None:
    (tmp_path / "lib").mkdir()
    assert "### lib" not in _pack(tmp_path, ["lib/"])


def test_the_budget_holds(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("a" * 400)
    (tmp_path / "b.py").write_text("b" * 400)
    text = _pack(tmp_path, ["a.py", "b.py"], budget=600)
    assert "aaaa" in text and "bbbb" not in text
    assert "b.py" in text


def test_nothing_to_show_is_empty(tmp_path: Path) -> None:
    assert _pack(tmp_path, []) == ""


def test_changed_between(engine: Engine) -> None:
    old = gitops.head(engine.worktree)
    (engine.worktree / "n.py").write_text("n = 1\n")
    new = gitops.commit_all(engine.worktree, "s", {})
    assert new is not None
    assert gitops.changed_between(engine.worktree, old, new) == ["n.py"]
    assert gitops.changed_between(engine.worktree, "deadbeef", new) == []


def test_the_implementer_gets_the_planned_files(engine: Engine, fake_clis: FakeClis) -> None:
    (engine.worktree / "retry.py").write_text("retries = 1\n")
    doc = engine.ticket()
    doc.meta.touches = ["retry.py", "new_thing.py"]
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits={"retry.py": "r = 2\n"})
    steps.run_job("7b55e0c1", steps=2)
    prompt = fake_clis.calls("codex")[0]["argv"][-1]
    assert "### retry.py" in prompt and "retries = 1" in prompt
    assert "new_thing.py" in prompt


def test_the_planner_gets_no_file_pack(engine: Engine, fake_clis: FakeClis) -> None:
    (engine.worktree / "retry.py").write_text("retries = 1\n")
    doc = engine.ticket()
    doc.meta.touches = ["retry.py"]
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    steps.run_job("7b55e0c1", steps=1)
    assert "### retry.py" not in " ".join(fake_clis.calls("claude")[0]["argv"])


def test_a_new_session_is_told_how_to_delegate(engine: Engine, fake_clis: FakeClis) -> None:
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    steps.run_job("7b55e0c1", steps=1)
    assert prompts.DELEGATION in " ".join(fake_clis.calls("claude")[0]["argv"])


def test_a_resumed_session_hears_what_changed(engine: Engine) -> None:
    from kengash_ai.model import Ticket

    meta: Ticket = engine.ticket().meta
    text = prompts.resumed_prompt(
        meta, {}, step="review_code", diff_stat="", changed=["lib/a.dart", "lib/b.dart"]
    )
    assert "Changed since your last turn" in text and "lib/b.dart" in text


def test_nothing_changed_says_nothing(engine: Engine) -> None:
    text = prompts.resumed_prompt(engine.ticket().meta, {}, step="review_code", diff_stat="")
    assert "Changed since" not in text


def test_the_step_end_records_the_commit_each_role_saw(engine: Engine, fake_clis: FakeClis) -> None:
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    steps.run_job("7b55e0c1", steps=1)
    state = runtime.load_ticket_state(engine.paths, "7b55e0c1")
    assert state.seen["planner"] == gitops.head(engine.worktree)


def _decide(paths: StorePaths, text: str) -> None:
    memory.add(paths, text, "because", decision=True, project="payments-api", by="t")


def test_memory_tags_a_path_that_is_gone(store_paths: StorePaths, registered_repo: Path) -> None:
    (registered_repo / "lib").mkdir()
    (registered_repo / "lib" / "here.dart").write_text("x\n")
    _decide(store_paths, "Keep state in lib/here.dart")
    _decide(store_paths, "Tokens live in lib/gone.dart")
    digest = memory.digest(store_paths, "payments-api", root=registered_repo)
    assert "[stale? path gone: lib/gone.dart]" in digest
    assert "stale? path gone: lib/here.dart" not in digest


def test_memory_without_a_root_tags_nothing(store_paths: StorePaths, registered_repo: Path) -> None:
    _decide(store_paths, "Tokens live in lib/gone.dart")
    assert "stale?" not in memory.digest(store_paths, "payments-api")


def test_a_url_is_no_path(store_paths: StorePaths, registered_repo: Path) -> None:
    _decide(store_paths, "See https://example.com/docs/page.html for the rule")
    assert "stale?" not in memory.digest(store_paths, "payments-api", root=registered_repo)


def test_the_memory_lead_says_the_code_wins() -> None:
    assert "the code wins" in prompts.MEMORY_LEAD


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads every file")
def test_an_unreadable_file_is_named_and_the_step_goes_on(tmp_path: Path) -> None:
    (tmp_path / "locked.py").write_text("x = 1\n")
    (tmp_path / "locked.py").chmod(0)
    (tmp_path / "ok.py").write_text("y = 2\n")
    text = _pack(tmp_path, ["locked.py", "ok.py"])
    assert "locked.py (unreadable)" in text
    assert "y = 2" in text
