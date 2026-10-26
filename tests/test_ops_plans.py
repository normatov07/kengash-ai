from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from kengash_ai.model import NeedsUser, PlanMode, PlanStatus, UserError
from kengash_ai.ops import plans, records
from kengash_ai.store import StorePaths, documents

PROMPT = "Make webhook keys rotatable.\n## Goal\nas the user typed it\n"
Events = Callable[[], list[dict[str, Any]]]


def new(repo: Path, mode: PlanMode = PlanMode.direct) -> str:
    return plans.new_plan(
        PROMPT, title="Rotatable keys", mode=mode, project=None, cwd=repo, by="claude"
    ).id


def test_new_plan_keeps_the_prompt_verbatim(
    store_paths: StorePaths,
    registered_repo: Path,
    journal_events: Events,
    run_git: Callable[..., str],
) -> None:
    result = plans.new_plan(
        PROMPT,
        title=" Rotatable keys ",
        mode=PlanMode.grill,
        project=None,
        cwd=registered_repo,
        by="claude",
    )
    assert (result.project, result.status) == ("payments-api", "grilling")
    shown = plans.show_plan(result.id, project=None)
    assert shown.sections["Prompt"] == PROMPT.rstrip("\n")
    assert (shown.meta["title"], shown.meta["review"]["max"]) == ("Rotatable keys", 2)
    assert shown.text.startswith(f"---\nid: {result.id}\n")
    event = journal_events()[-1]
    assert (event["type"], event["plan"], event["mode"], event["by"]) == (
        "plan.created",
        result.id,
        "grill",
        "claude",
    )
    assert f"harness: plan new {result.id}" in run_git(store_paths.home, "log", "--format=%s")


@pytest.mark.parametrize(
    ("prompt", "title", "message"),
    [("  ", "Keys", "the prompt is empty"), ("Rotate.", "Two\nlines", "title: must be one line")],
)
def test_new_plan_refuses_bad_input(
    registered_repo: Path, prompt: str, title: str, message: str
) -> None:
    with pytest.raises(UserError, match=message):
        plans.new_plan(
            prompt, title=title, mode=PlanMode.direct, project=None, cwd=registered_repo, by="x"
        )


def test_new_plan_needs_a_project(registered_repo: Path) -> None:
    with pytest.raises(UserError, match="no project here"):
        plans.new_plan(
            PROMPT,
            title="Keys",
            mode=PlanMode.direct,
            project=None,
            cwd=registered_repo.parent,
            by="x",
        )


def test_save_replaces_sections_and_makes_a_draft(registered_repo: Path) -> None:
    plan_id = new(registered_repo, PlanMode.grill)
    markdown = "## Goal\nShip it.\n\n## Scope\nKeys only.\n"
    result = plans.save_plan(plan_id, markdown, project=None, by="x")
    assert (result.status, result.sections) == ("draft", ["Goal", "Scope"])
    sections = plans.show_plan(plan_id, project=None).sections
    assert (sections["Goal"], sections["Scope"]) == ("Ship it.", "Keys only.")
    assert sections["Prompt"] == PROMPT.rstrip("\n")


@pytest.mark.parametrize(
    ("markdown", "message"),
    [
        ("## Prompt\nnew words", "never changes"),
        ("## Goals\nx", "unknown section 'Goals'"),
        ("\n", "no sections given"),
    ],
)
def test_save_refuses_bad_sections(registered_repo: Path, markdown: str, message: str) -> None:
    plan_id = new(registered_repo)
    with pytest.raises(UserError, match=message):
        plans.save_plan(plan_id, markdown, project=None, by="x")


def test_approval_needs_a_review_or_an_explicit_skip(
    registered_repo: Path, journal_events: Events
) -> None:
    plan_id = new(registered_repo)
    with pytest.raises(NeedsUser, match="--skip-review"):
        plans.approve_plan(plan_id, skip_review=False, project=None, by="x")
    result = plans.approve_plan(plan_id, skip_review=True, project=None, by="x")
    assert (result.status, result.review_skipped) == ("approved", True)
    assert plans.show_plan(plan_id, project=None).meta["review"]["skipped"] is True
    assert journal_events()[-1]["review_skipped"] is True


def test_quick_plans_and_review_max_zero_need_no_skip(
    store_paths: StorePaths, registered_repo: Path
) -> None:
    quick = new(registered_repo, PlanMode.quick)
    assert plans.approve_plan(quick, skip_review=False, project=None, by="x").status == "approved"
    store_paths.project("payments-api").settings.write_text(
        "plan.review_max: 0\n", encoding="utf-8"
    )
    direct = new(registered_repo)
    approved = plans.approve_plan(direct, skip_review=False, project=None, by="x")
    assert (approved.status, approved.review_skipped) == ("approved", False)


def test_only_draft_plans_can_be_approved(registered_repo: Path) -> None:
    plan_id = new(registered_repo, PlanMode.grill)
    with pytest.raises(UserError, match="is grilling"):
        plans.approve_plan(plan_id, skip_review=True, project=None, by="x")


def test_rejection_is_logged_and_saving_revives_the_plan(registered_repo: Path) -> None:
    plan_id = new(registered_repo)
    assert plans.reject_plan(plan_id, "too broad", project=None, by="x").status == "rejected"
    log = plans.show_plan(plan_id, project=None).sections["Review log"]
    assert log.endswith("rejected by the user: too broad")
    assert plans.save_plan(plan_id, "## Goal\nNarrower.", project=None, by="x").status == "draft"


def test_unknown_plans_and_projects(registered_repo: Path) -> None:
    with pytest.raises(UserError, match="unknown plan: deadbeef"):
        plans.show_plan("deadbeef", project=None)
    with pytest.raises(UserError, match="unknown project: nope"):
        plans.show_plan("deadbeef", project="nope")


def reviewed(store_paths: StorePaths, plan_id: str, round: int, verdict: str | None) -> None:
    _, path = records.locate_plan(store_paths, plan_id, None)
    doc = records.load_plan(path)
    doc.meta.status = PlanStatus.in_review
    doc.meta.review.round, doc.meta.review.verdict = round, verdict  # type: ignore[assignment]
    documents.save_plan(store_paths.project("payments-api"), doc)


def test_approve_refuses_a_failed_round_with_rounds_left(
    store_paths: StorePaths, registered_repo: Path
) -> None:
    plan_id = new(registered_repo)
    reviewed(store_paths, plan_id, 1, "fail")
    with pytest.raises(NeedsUser, match="failed review round 1 of 2"):
        plans.approve_plan(plan_id, skip_review=False, project=None, by="x")
    skipped = plans.approve_plan(plan_id, skip_review=True, project=None, by="x")
    assert skipped.review_skipped is True


def test_approve_accepts_a_pass_or_used_up_rounds(
    store_paths: StorePaths, registered_repo: Path
) -> None:
    passed, used_up = new(registered_repo), new(registered_repo)
    reviewed(store_paths, passed, 1, "pass")
    reviewed(store_paths, used_up, 2, None)  # saved again after the last round failed
    for plan_id in (passed, used_up):
        result = plans.approve_plan(plan_id, skip_review=False, project=None, by="x")
        assert (result.status, result.review_skipped) == ("approved", False)
