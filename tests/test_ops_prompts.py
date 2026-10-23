"""Step prompts, section text and log lines (SP3 spec §8.2)."""

from collections.abc import Callable
from datetime import UTC, datetime

from super_harness.model import Doc, Finding, Ticket
from super_harness.ops import prompts
from super_harness.store import StorePaths
from super_harness.store.seed import ensure_project, ensure_store

Make = Callable[..., Doc[Ticket]]

SECTIONS = {
    "Scope": "Retry webhooks.",
    "Acceptance": "- [ ] retries 3 times",
    "Handoff": "Plan: add retry.py",
    "Findings": "- low · a.py:1 · unclear name · rename",
    "Log": "- old",
}


def test_new_prompt_inlines_the_ticket(make_ticket: Make) -> None:
    ticket = make_ticket(loop=2, loop_max=3).meta
    text = prompts.new_prompt(
        ticket,
        SECTIONS,
        "Webhooks retry.",
        role="code-reviewer",
        step="review_code",
        diff_stat=" a.py | 2 +-",
    )
    assert (
        text.splitlines()[0] == 'You are the code-reviewer for ticket 7b55e0c1 "Rotate keys", '
        "loop 2 of 3, step review_code."
    )
    assert text.splitlines()[1] == prompts.INSTRUCTIONS["review_code"]
    assert (
        "## Goal (plan a1b2c3d4)\nWebhooks retry." in text and "## Diff stat\n a.py | 2 +-" in text
    )
    assert "## Log" not in text and text.endswith("Reply with JSON that matches the schema.")


def test_resumed_prompts_carry_only_the_delta(make_ticket: Make) -> None:
    ticket = make_ticket(loop=2, loop_max=3).meta
    work = prompts.resumed_prompt(ticket, SECTIONS, step="implement", diff_stat="x")
    assert work.splitlines()[0] == f"Loop 2, step implement: {prompts.INSTRUCTIONS['implement']}"
    assert "## Findings" in work and "## Handoff" not in work and "## Scope" not in work
    review = prompts.resumed_prompt(ticket, SECTIONS, step="review_code", diff_stat=" a.py | 2 +-")
    assert "## Handoff" in review and "## Diff stat" in review and "## Findings" not in review


def test_sections_and_log_lines() -> None:
    assert prompts.handoff_text("\n".join(f"l{i}" for i in range(20))).splitlines()[-1] == "l14"
    finding = Finding(severity="high", file="", line=0, issue="token=abc123def456ghi789", fix="f")
    assert prompts.findings_text([finding]) == "- high · -:0 · token=[REDACTED] · f"
    at = datetime(2026, 10, 23, 9, 5, tzinfo=UTC)
    assert prompts.log_line(at, "plan", "planner", "claude", None, "pass", 1200) == (
        "- 2026-10-23 09:05 · plan · planner · claude/default · pass · 1200"
    )
    assert (prompts.output_kind("run_tests"), prompts.profile("implement")) == (
        "review",
        "edit_worktree",
    )


def test_role_skills_come_from_the_package_by_default(store_paths: StorePaths) -> None:
    ensure_store(store_paths)
    ensure_project(store_paths, "payments-api")
    text = prompts.role_skill(store_paths, "payments-api", "review-code")
    assert text is not None and text.strip() and not text.startswith("---")
