"""A merge conflict settled inside its ticket (SP19 spec)."""

from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import Engine, FakeClis, write_settings

from kengash_ai import gitops, settings
from kengash_ai.adapters.antigravity import Antigravity
from kengash_ai.adapters.claude import Claude
from kengash_ai.model import StepRequest, UserError
from kengash_ai.ops import checks, hygiene, merging, prompts, steps
from kengash_ai.store import documents, runtime

MARKER = "<<<<<<< "
Git = Callable[..., str]


def edit(where: Path, name: str, text: str) -> None:
    path = where / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    gitops.commit_all(where, f"edit {name}", {})


def awaiting_merge(engine: Engine) -> None:
    doc = engine.ticket()
    doc.meta.status, doc.meta.step = "in_process/awaiting_merge", None
    documents.save_ticket(engine.paths.project(engine.slug), doc)


def conflict(engine: Engine, name: str = "README.md") -> None:
    edit(engine.worktree, name, "ticket\n")
    edit(engine.repo, name, "main\n")
    awaiting_merge(engine)


def set_values(engine: Engine, **values: object) -> None:
    settings.set_values(
        engine.paths, engine.slug, {k.replace("__", "."): v for k, v in values.items()}
    )


def test_replay_leaves_markers_and_no_operation_in_progress(engine: Engine, run_git: Git) -> None:
    conflict(engine)
    assert gitops.rebase(engine.worktree, "main") == ["README.md"]
    assert gitops.replay_onto(engine.worktree, "main", "7b55e0c1") == ["README.md"]
    assert MARKER in (engine.worktree / "README.md").read_text(encoding="utf-8")
    assert "rebase" not in run_git(engine.worktree, "status").lower()
    assert "cherry-pick" not in run_git(engine.worktree, "status").lower()
    assert gitops.head(engine.worktree) == gitops.head(engine.repo)


def test_replay_keeps_nonconflicting_changes(engine: Engine) -> None:
    edit(engine.worktree, "new_file.py", "x = 1\n")
    conflict(engine)
    gitops.replay_onto(engine.worktree, "main", "7b55e0c1")
    assert (engine.worktree / "new_file.py").read_text(encoding="utf-8") == "x = 1\n"


def test_replay_squashes_many_commits_into_one_pass(engine: Engine, run_git: Git) -> None:
    for number in range(3):
        edit(engine.worktree, "README.md", f"ticket {number}\n")
    edit(engine.repo, "README.md", "main\n")
    assert gitops.replay_onto(engine.worktree, "main", "7b55e0c1") == ["README.md"]
    (engine.worktree / "README.md").write_text("both\n", encoding="utf-8")
    gitops.commit_all(engine.worktree, "resolved", {})
    assert int(run_git(engine.worktree, "rev-list", "--count", "main..HEAD")) == 1
    assert gitops.contains(engine.worktree, "main", "HEAD")


def test_replay_backup_ref_is_kept_and_dropped(engine: Engine, run_git: Git) -> None:
    conflict(engine)
    tip = gitops.head(engine.worktree)
    gitops.replay_onto(engine.worktree, "main", "7b55e0c1")
    assert run_git(engine.repo, "rev-parse", "refs/kengash/conflict/7b55e0c1").strip() == tip
    gitops.drop_conflict_ref(engine.repo, "7b55e0c1")
    assert "refs/kengash" not in run_git(engine.repo, "for-each-ref")
    gitops.drop_conflict_ref(engine.repo, "7b55e0c1")  # nothing to drop is fine


def test_with_markers_finds_only_marked_files(tmp_path: Path) -> None:
    (tmp_path / "a").write_text("<<<<<<< HEAD\nx\n", encoding="utf-8")
    (tmp_path / "b").write_text("clean <<<<<<< not at the start\n", encoding="utf-8")
    assert gitops.with_markers(tmp_path, ["a", "b", "gone"]) == ["a"]


def test_a_conflict_leaves_markers_and_costs_no_loop(engine: Engine) -> None:
    conflict(engine)
    with pytest.raises(UserError, match=r"conflict in README.md; 7b55e0c1 sent back to implement"):
        merging.merge_ticket("7b55e0c1", project=None, by="user")
    after = engine.ticket()
    assert (after.meta.status, after.meta.step, after.meta.loop) == (
        "in_queue/ready",
        "implement",
        1,
    )
    assert "remove every marker" in after.sections["Findings"]
    assert MARKER in (engine.worktree / "README.md").read_text(encoding="utf-8")
    state = runtime.load_ticket_state(engine.paths, "7b55e0c1")
    assert (state.conflicts, state.conflict_turns) == (["README.md"], 1)


def test_conflict_turns_run_out_into_the_loop_cap(engine: Engine) -> None:
    set_values(engine, merge__conflict_turns=0)
    doc = engine.ticket()
    doc.meta.loop = doc.meta.loop_max
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    conflict(engine)
    with pytest.raises(UserError, match="waits for approval at the loop cap"):
        merging.merge_ticket("7b55e0c1", project=None, by="user")
    assert engine.ticket().meta.status == "in_process/needs_approval"


def test_generated_only_conflict_lands_without_a_worker(
    engine: Engine, fake_clis: FakeClis
) -> None:
    set_values(engine, project__generate_cmd="echo generated > gen/out.g.dart")
    conflict(engine, "gen/out.g.dart")
    merged = merging.merge_ticket("7b55e0c1", project=None, by="user")
    assert merged.commits == 1
    assert engine.ticket().meta.status == "done/merged"
    assert (engine.repo / "gen" / "out.g.dart").read_text(encoding="utf-8") == "generated\n"
    assert fake_clis.calls("claude") == [] and fake_clis.calls("codex") == []


def test_a_generated_conflict_beside_a_real_one_goes_to_the_worker(engine: Engine) -> None:
    set_values(engine, project__generate_cmd="echo generated > gen/out.g.dart")
    edit(engine.worktree, "gen/out.g.dart", "ticket\n")
    edit(engine.repo, "gen/out.g.dart", "main\n")
    conflict(engine)
    with pytest.raises(UserError, match=r"conflict in README\.md;"):
        merging.merge_ticket("7b55e0c1", project=None, by="user")
    assert MARKER not in (engine.worktree / "gen" / "out.g.dart").read_text(encoding="utf-8")
    assert runtime.load_ticket_state(engine.paths, "7b55e0c1").conflicts == ["README.md"]


def test_generator_failure_sends_back(engine: Engine) -> None:
    set_values(engine, project__generate_cmd="false")
    conflict(engine, "gen/out.g.dart")
    with pytest.raises(UserError, match="regenerating failed"):
        merging.merge_ticket("7b55e0c1", project=None, by="user")
    after = engine.ticket()
    assert (after.meta.status, after.meta.loop) == ("in_queue/ready", 1)
    with pytest.raises(UserError, match="merge needs awaiting_merge"):
        merging.merge_ticket("7b55e0c1", project=None, by="user")


def test_generated_conflict_without_a_generator_goes_to_the_worker(engine: Engine) -> None:
    conflict(engine, "gen/out.g.dart")
    with pytest.raises(UserError, match=r"conflict in gen/out\.g\.dart"):
        merging.merge_ticket("7b55e0c1", project=None, by="user")


def resolve_step(engine: Engine, fake_clis: FakeClis, *edits: dict[str, str]) -> steps.JobEnd:
    doc = engine.ticket()
    doc.meta.status = "in_process/under_implementation"
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    for files in edits:
        fake_clis.queue("codex", fixture="codex/work_resume.jsonl", edits=files)
    return steps.run_job("7b55e0c1", steps=1)


def sent_back(engine: Engine) -> None:
    conflict(engine)
    with pytest.raises(UserError):
        merging.merge_ticket("7b55e0c1", project=None, by="user")


def test_resolved_conflict_merges(engine: Engine, fake_clis: FakeClis, run_git: Git) -> None:
    sent_back(engine)
    resolve_step(engine, fake_clis, {"README.md": "both\n"})
    state = runtime.load_ticket_state(engine.paths, "7b55e0c1")
    assert state.conflicts == []
    assert run_git(engine.worktree, "status", "--porcelain") == ""
    assert prompts.RETRY_NOTE not in fake_clis.calls("codex")[0]["argv"][-1]
    awaiting_merge(engine)
    merging.merge_ticket("7b55e0c1", project=None, by="user")
    assert (engine.repo / "README.md").read_text(encoding="utf-8") == "both\n"
    assert "refs/kengash" not in run_git(engine.repo, "for-each-ref")


def test_marker_left_gets_a_repair_turn(engine: Engine, fake_clis: FakeClis) -> None:
    sent_back(engine)
    left = (engine.worktree / "README.md").read_text(encoding="utf-8")
    resolve_step(engine, fake_clis, {"README.md": left}, {"README.md": "both\n"})
    calls = fake_clis.calls("codex")
    assert len(calls) == 2 and "still hold conflict markers: README.md" in calls[1]["argv"][-1]
    assert engine.ticket().sections["Log"].count("· implement ·") == 1


def test_marker_left_twice_fails_with_work_kept(engine: Engine, fake_clis: FakeClis) -> None:
    sent_back(engine)
    left = (engine.worktree / "README.md").read_text(encoding="utf-8")
    end = resolve_step(engine, fake_clis, {"README.md": left}, {"README.md": left})
    assert end.status == "in_process/failed"
    assert MARKER in (engine.worktree / "README.md").read_text(encoding="utf-8")


def _request(engine: Engine, **fields: object) -> StepRequest:
    data: dict[str, object] = {
        "role": "implementer",
        "cwd": engine.worktree,
        "prompt": "p",
        "output": "work",
        "profile": "edit_worktree",
        "timeout_s": 60,
        "log": engine.worktree / "log",
        **fields,
    }
    return StepRequest.model_validate(data)


def test_claude_may_run_project_commands(engine: Engine) -> None:
    argv = Claude().command(_request(engine, commands=["python3 tools/gen.py"]))
    assert "Bash(python3 tools/gen.py:*)" in argv


def test_agy_may_run_project_commands_without_operators(engine: Engine) -> None:
    request = _request(engine, test_cmd="pytest", commands=["python3 tools/gen.py", "a && b"])
    argv = " ".join(Antigravity().command(request))
    assert "command(python3 tools/gen.py)" in argv and "a && b)" not in argv


def test_project_allows_generator_and_commands(engine: Engine) -> None:
    set_values(engine, project__generate_cmd="gen", project__commands=["one"])
    resolved = settings.load(engine.paths, engine.slug)
    assert resolved.project.allowed == ["one", "gen"]
    block = prompts.checks_block("t", "", resolved.project.allowed)
    assert "- project: `one`" in block and "- project: `gen`" in block


def test_checks_start_with_the_generator(engine: Engine) -> None:
    set_values(engine, project__test_cmd="pytest -q", project__generate_cmd="gen")
    resolved = settings.load(engine.paths, engine.slug)
    assert checks.request(resolved, engine.worktree, engine.worktree / "l").test_cmd == (
        "gen && pytest -q"
    )


def test_checks_without_a_generator_are_unchanged(engine: Engine) -> None:
    set_values(engine, project__test_cmd="pytest -q")
    resolved = settings.load(engine.paths, engine.slug)
    assert checks.request(resolved, engine.worktree, engine.worktree / "l").test_cmd == "pytest -q"


def at_review(engine: Engine) -> None:
    doc = engine.ticket()
    doc.meta.status, doc.meta.step = "in_process/under_review", "review_code"
    documents.save_ticket(engine.paths.project(engine.slug), doc)


REVIEW = {"verdict": "pass", "summary": "Good.", "findings": []}


def test_review_rebases_a_moved_base(
    engine: Engine, fake_clis: FakeClis, journal_events: object
) -> None:
    edit(engine.worktree, "mine.py", "x = 1\n")
    edit(engine.repo, "theirs.py", "y = 2\n")
    at_review(engine)
    fake_clis.queue("claude", stdout=fake_clis.claude_output(REVIEW))
    steps.run_job("7b55e0c1", steps=1)
    assert gitops.contains(engine.worktree, "main", "HEAD")
    assert (engine.worktree / "theirs.py").is_file()


def test_review_leaves_a_conflicting_branch_alone(engine: Engine, fake_clis: FakeClis) -> None:
    edit(engine.worktree, "README.md", "ticket\n")
    tip = gitops.head(engine.worktree)
    edit(engine.repo, "README.md", "main\n")
    at_review(engine)
    fake_clis.queue("claude", stdout=fake_clis.claude_output(REVIEW))
    steps.run_job("7b55e0c1", steps=1)
    assert gitops.head(engine.worktree) == tip
    assert (engine.worktree / "README.md").read_text(encoding="utf-8") == "ticket\n"


@pytest.mark.parametrize("cap", [250_000, 1_000_000])
def test_doctor_treats_old_token_caps_as_old(engine: Engine, cap: int) -> None:
    write_settings(engine.paths, f"tokens.per_ticket_max: {cap}\n", (engine.slug,))
    assert "tokens.per_ticket_max" in hygiene.old_defaults(engine.paths, engine.slug)
    hygiene.fix_old_defaults(engine.paths, engine.slug)
    assert settings.load(engine.paths, engine.slug).tokens.per_ticket_max == 3_000_000


def test_a_refused_settle_commit_sends_back(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_values(engine, project__generate_cmd="echo generated > gen/out.g.dart")
    conflict(engine, "gen/out.g.dart")

    def refused(cwd: Path, subject: str, trailers: dict[str, str]) -> str | None:
        raise gitops.CommitFailed("hook said no", "hook said no")

    monkeypatch.setattr(gitops, "commit_all", refused)
    with pytest.raises(UserError, match="commit failed after rebase"):
        merging.merge_ticket("7b55e0c1", project=None, by="user")
    assert engine.ticket().meta.status == "in_queue/ready"
