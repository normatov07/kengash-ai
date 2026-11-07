"""Step prompts, section text and log lines (SP3 spec §8.2)."""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from kengash_ai.model import Decision, Doc, Finding, SentBack, Settings, Ticket
from kengash_ai.ops import prompts
from kengash_ai.store import StorePaths
from kengash_ai.store.seed import ensure_project, ensure_store

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


def test_new_prompt_puts_memory_first(make_ticket: Make) -> None:
    ticket = make_ticket().meta
    text = prompts.new_prompt(
        ticket,
        SECTIONS,
        "Webhooks retry.",
        role="implementer",
        step="implement",
        diff_stat="",
        memory="Decisions (DECISIONS.md, newest last):\n- keyring over env var",
    )
    assert text.index("## Memory") < text.index("## Goal")
    assert f"## Memory\n{prompts.MEMORY_LEAD}\n\nDecisions" in text
    plain = prompts.new_prompt(
        ticket, SECTIONS, "Webhooks retry.", role="implementer", step="implement", diff_stat=""
    )
    assert "## Memory" not in plain


def test_resumed_prompt_has_no_memory(make_ticket: Make) -> None:
    ticket = make_ticket().meta
    assert "## Memory" not in prompts.resumed_prompt(
        ticket, SECTIONS, step="implement", diff_stat=""
    )


def test_decision_lines_dedupe_then_cap() -> None:
    def proposal(text: str, rejected: str = "") -> Decision:
        return Decision(decision=text, why="y", rejected=rejected)

    proposed = [proposal("A"), proposal("b", "c"), proposal("c"), proposal("d"), proposal("e")]
    assert prompts.decision_lines("- a. why: x.", proposed).splitlines() == [
        "- a. why: x.",
        "- b. why: y. rejected: c.",
        "- c. why: y.",
        "- d. why: y.",
    ]
    full = "\n".join(f"- old {n}. why: x." for n in range(5))
    last = prompts.decision_lines(full, proposed[1:]).splitlines()[-1]
    assert last == "- b. why: y. rejected: c."
    assert len(prompts.decision_lines(full, proposed[1:]).splitlines()) == 6


def test_review_prompts_show_decisions(make_ticket: Make) -> None:
    ticket = make_ticket().meta
    sections = {**SECTIONS, "Decisions": "- keep X. why: y."}
    new = prompts.new_prompt(
        ticket, sections, "Goal.", role="code-reviewer", step="review_code", diff_stat="d"
    )
    assert new.index("## Handoff") < new.index("## Decisions\n- keep X. why: y.")
    resumed = prompts.resumed_prompt(ticket, sections, step="review_code", diff_stat="d")
    assert "## Decisions\n- keep X. why: y." in resumed


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


def test_read_steps_reply_with_plan_output() -> None:
    assert [prompts.output_kind(s) for s in ("plan", "implement", "review_plan")] == [
        "plan",
        "work",
        "review",
    ]


def test_role_skills_come_from_the_package_by_default(store_paths: StorePaths) -> None:
    ensure_store(store_paths)
    ensure_project(store_paths, "payments-api")
    text = prompts.role_skill(store_paths, "payments-api", "review-code")
    assert text is not None and text.strip() and not text.startswith("---")


def test_custom_step_prompts_follow_their_kind() -> None:
    agents = {"x-agent": {"cli": "claude", "skill": "x-agent"}}
    steps = {
        name: {"role": "x-agent", "kind": kind, "does": "Do the thing."}
        for name, kind in (("advise", "read"), ("tidy", "edit"), ("perf_review", "review"))
    }
    settings = Settings.model_validate({"agents": agents, "steps": steps})
    assert prompts.instruction(settings, "advise") == "Do the thing. Do not edit files."
    assert prompts.instruction(settings, "tidy") == "Do the thing. Do not commit; kengash commits."
    assert prompts.instruction(settings, "perf_review") == (
        "Do the thing. Read the changes with read-only git; fail only for real problems."
    )
    assert prompts.instruction(settings, "implement") == prompts.INSTRUCTIONS["implement"]
    assert [prompts.output_kind(s, settings) for s in ("advise", "tidy", "perf_review")] == [
        "plan",
        "work",
        "review",
    ]
    assert [prompts.profile(s, settings) for s in ("advise", "tidy", "perf_review")] == [
        "read_only",
        "edit_worktree",
        "read_only",
    ]


CHECKS = (
    "kengash runs these in the worktree after editing steps; each must exit 0:\n"
    "- tests: `flutter test`\n- lint: `flutter analyze`"
)
CHECK_OUTPUT = "`flutter analyze` exit 1: info • x\n```text\ninfo • x\n```"


def test_checks_block_names_the_commands_that_are_set() -> None:
    assert prompts.checks_block("flutter test", "flutter analyze") == CHECKS
    assert prompts.checks_block("", "") == ""
    assert prompts.checks_block("", "ruff check") == (
        "kengash runs these in the worktree after editing steps; each must exit 0:\n"
        "- lint: `ruff check`"
    )


def test_new_prompts_name_the_checks(make_ticket: Make) -> None:
    text = prompts.new_prompt(
        make_ticket().meta,
        SECTIONS,
        "Webhooks retry.",
        role="implementer",
        step="implement",
        diff_stat="",
        feedback=prompts.Feedback(checks=CHECKS, editing=True),
    )
    assert f"## Checks\n{CHECKS}" in text
    assert text.index("## Findings") < text.index("## Checks")


def test_a_check_sent_back_head_replaces_the_instruction(make_ticket: Make) -> None:
    ticket = make_ticket(loop=3, loop_max=5).meta
    sent = SentBack(step="run_tests", summary="lint failed (exit 1)")
    line = prompts.sent_back_line(sent, check=True)
    text = prompts.resumed_prompt(
        ticket,
        {**SECTIONS, "Check output": CHECK_OUTPUT},
        step="implement",
        diff_stat="",
        feedback=prompts.Feedback(checks=CHECKS, sent_back=line, editing=True),
    )
    assert text.splitlines()[0] == (
        "Loop 3, step implement: run_tests sent this back: lint failed (exit 1). "
        "Fix every Finding below, then run the failing check."
    )
    assert f"## Check output\n{CHECK_OUTPUT}" in text and f"## Checks\n{CHECKS}" in text


def test_a_review_sent_back_line_has_no_check_clause() -> None:
    sent = SentBack(step="review_code", summary="pubspec declares no fonts")
    assert prompts.sent_back_line(sent, check=False) == (
        "review_code sent this back: pubspec declares no fonts. Fix every Finding below."
    )


def test_the_users_answer_follows_the_instruction(make_ticket: Make) -> None:
    ticket = make_ticket(loop=2, loop_max=3).meta
    line = prompts.sent_back_line(SentBack(step="user", summary="assets are in raw/"), check=False)
    assert line == "The user answered: assets are in raw/."
    feedback = prompts.Feedback(sent_back=line, user=True, editing=True)
    resumed = prompts.resumed_prompt(
        ticket, SECTIONS, step="implement", diff_stat="", feedback=feedback
    )
    told = prompts.INSTRUCTIONS["implement"]
    assert resumed.splitlines()[:2] == [f"Loop 2, step implement: {told}", line]
    new = prompts.new_prompt(
        ticket, SECTIONS, "g", role="implementer", step="implement", diff_stat="", feedback=feedback
    )
    assert new.splitlines()[1:3] == [told, line]


def test_reviewers_get_checks_but_not_check_output(make_ticket: Make) -> None:
    ticket = make_ticket().meta
    sections = {**SECTIONS, "Check output": CHECK_OUTPUT}
    feedback = prompts.Feedback(checks=CHECKS)
    review = prompts.resumed_prompt(
        ticket, sections, step="review_code", diff_stat=" a | 1", feedback=feedback
    )
    new = prompts.new_prompt(
        ticket,
        sections,
        "g",
        role="code-reviewer",
        step="review_code",
        diff_stat="x",
        feedback=feedback,
    )
    for text in (review, new):
        assert "## Checks" in text and "## Check output" not in text


def test_sent_back_lines_are_flat_redacted_and_short() -> None:
    summary = "first line\nsecond token=abc123def456ghi789 " + "x" * 400
    line = prompts.sent_back_line(SentBack(step="review_code", summary=summary), check=False)
    assert "\n" not in line and "abc123def456ghi789" not in line and "[REDACTED]" in line
    assert len(line) <= len("review_code sent this back: . Fix every Finding below.") + 300


def test_fix_prompt_carries_the_headline_and_output() -> None:
    output = "`flutter test` exit 1: error: boom\n```text\nerror: boom\n```"
    text = prompts.fix_prompt(output, turn=1, turns=2)
    assert text.splitlines()[0] == (
        "kengash ran the checks after your reply (fix turn 1 of 2): "
        "`flutter test` exit 1: error: boom"
    )
    assert f"## Check output\n{output}" in text
    assert text.endswith(
        "Fix the cause, then rerun that command if your tools allow. "
        "Reply again with JSON that matches the schema."
    )


def test_check_log_line() -> None:
    at = datetime(2026, 11, 7, 10, 1, tzinfo=UTC)
    assert prompts.check_log_line(at, "fail", "lint failed (exit 1)") == (
        "- 2026-11-07 10:01 · checks · kengash · shell/default · fail · 0 · lint failed (exit 1)"
    )


@pytest.mark.parametrize(
    ("handoff", "said"),
    [
        ("Files: x\nBLOCKED: needs the login", "needs the login"),
        ("- BLOCKED: needs the login", "needs the login"),
        ("**BLOCKED:** needs the login", "needs the login"),
        ("BLOCKED: none", ""),
        ("BLOCKED: n/a", ""),
        ("BLOCKED: -", ""),
        ("BLOCKED: Nothing.", ""),
        ("BLOCKED:", ""),
        ("Not blocked at all", ""),
    ],
)
def test_blocked_line_reads_real_blocks_only(handoff: str, said: str) -> None:
    assert prompts.blocked_line(handoff) == said
