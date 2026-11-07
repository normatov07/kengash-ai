"""What a step's CLI reads and what kengash writes back (SP3 spec §8.2, decision 25)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from kengash_ai.model import (
    BUILTIN_KINDS,
    PLAN_SECTIONS,
    Finding,
    Kind,
    OutputKind,
    Plan,
    Profile,
    ReviewOutput,
    SentBack,
    Settings,
    Ticket,
)
from kengash_ai.ops import skills
from kengash_ai.store.paths import StorePaths
from kengash_ai.store.redact import redact

HANDOFF_LINES = 15
INSTRUCTIONS = {
    "plan": "Write the implementation plan for this ticket: files, interfaces and tests. "
    "Do not edit files.",
    "review_plan": "Review the plan in the Handoff against the Scope and Acceptance; "
    "fail only for real gaps.",
    "implement": "Implement the ticket in this worktree, with tests. "
    "Do not commit; kengash commits.",
    "review_code": "Review the branch's changes against the Scope and Acceptance; "
    "read the diff with read-only git.",
    "security": "Review the branch's changes for security problems; "
    "read the diff with read-only git.",
    "docs": "Update the docs for the branch's changes. Do not commit; kengash commits.",
}
# the rule a custom step's one-line `does` gets, by kind (SP6 spec decision 2)
KIND_RULES = {
    "read": "Do not edit files.",
    "edit": "Do not commit; kengash commits.",
    "review": "Read the changes with read-only git; fail only for real problems.",
}
REPLY = "Reply with JSON that matches the schema."
PLAN_REVIEW = (
    "Review this plan against the user's Prompt and the code in this directory, read-only. "
    "Fail only for real gaps: a missed requirement, a wrong assumption, or a design that is "
    "unsafe or cannot be tested. For a finding about the plan itself, set file to its "
    "section name and line to 0."
)


CHECKS_HEAD = "kengash runs these in the worktree after editing steps; each must exit 0:"
SUMMARY_CHARS = 300


@dataclass(frozen=True)
class Feedback:
    """What a step's prompt says about the checks (SP15 spec §3.4): the Checks block, the
    sent-back line, whether that line is the user's answer, and whether the step edits (only
    editing steps get `## Check output`)."""

    checks: str = ""
    sent_back: str = ""
    user: bool = False
    editing: bool = False


NO_FEEDBACK = Feedback()


def checks_block(test_cmd: str, lint_cmd: str) -> str:
    """The `## Checks` body naming the commands that are set; empty when neither is."""
    rows = [
        f"- {name}: `{command.strip()}`"
        for name, command in (("tests", test_cmd), ("lint", lint_cmd))
        if command.strip()
    ]
    return "\n".join([CHECKS_HEAD, *rows]) if rows else ""


def sent_back_line(sent: SentBack, *, check: bool) -> str:
    """Why the step runs again: the failing step and its summary, or the user's answer."""
    summary = redact(_flat(sent.summary))[:SUMMARY_CHARS].rstrip(" .")
    if sent.step == "user":
        return f"The user answered: {summary}."
    then = ", then run the failing check" if check else ""
    return f"{sent.step} sent this back: {summary}. Fix every Finding below{then}."


def fix_prompt(check_output: str, *, turn: int, turns: int) -> str:
    """A fix turn's prompt: the failing check's headline, then its Check output."""
    headline = check_output.split("\n", 1)[0]
    return (
        f"kengash ran the checks after your reply (fix turn {turn} of {turns}): {headline}\n\n"
        f"## Check output\n{check_output}\n\n"
        "Fix the cause, then rerun that command if your tools allow. Reply again with JSON that "
        "matches the schema."
    )


def check_log_line(at: datetime, verdict: str, summary: str) -> str:
    """The ticket Log line of one in-step check run."""
    return f"- {at:%Y-%m-%d %H:%M} · checks · kengash · shell/default · {verdict} · 0 · {summary}"


def kind(step: str, settings: Settings | None = None) -> Kind | None:
    """What `step` does; without settings only the built-in steps are known."""
    return settings.kind_of(step) if settings is not None else BUILTIN_KINDS.get(step)


def output_kind(step: str, settings: Settings | None = None) -> OutputKind:
    return "review" if kind(step, settings) in ("review", "check") else "work"


def profile(step: str, settings: Settings | None = None) -> Profile:
    return "edit_worktree" if kind(step, settings) == "edit" else "read_only"


def instruction(settings: Settings, step: str) -> str:
    """What the step's CLI is told to do: the built-in line, or a custom step's `does`
    followed by its kind's rule."""
    custom = settings.steps.get(step)
    if custom is None:
        return INSTRUCTIONS.get(step, "")
    return f"{custom.does} {KIND_RULES[custom.kind]}"


def new_prompt(
    ticket: Ticket,
    sections: Mapping[str, str],
    goal: str,
    *,
    role: str,
    step: str,
    diff_stat: str,
    instruction: str | None = None,
    feedback: Feedback = NO_FEEDBACK,
) -> str:
    """A new session's prompt: who it is, the step, and the ticket inline; `instruction`
    defaults to the built-in step's."""
    head = (
        f'You are the {role} for ticket {ticket.id} "{ticket.title}", '
        f"loop {ticket.loop} of {ticket.loop_max}, step {step}."
    )
    blocks = [
        (f"Goal (plan {ticket.plan})", goal),
        ("Scope", sections.get("Scope", "")),
        ("Acceptance", sections.get("Acceptance", "")),
        ("Handoff", sections.get("Handoff", "")),
        ("Findings", sections.get("Findings", "")),
        *_check_blocks(sections, feedback),
        ("Diff stat", diff_stat),
    ]
    told = INSTRUCTIONS.get(step, "") if instruction is None else instruction
    lines = [head, told, *([feedback.sent_back] if feedback.sent_back else [])]
    return _join("\n".join(lines), blocks, REPLY)


def resumed_prompt(
    ticket: Ticket,
    sections: Mapping[str, str],
    *,
    step: str,
    diff_stat: str,
    instruction: str | None = None,
    review: bool | None = None,
    feedback: Feedback = NO_FEEDBACK,
) -> str:
    """A resumed session's prompt: the step, plus Findings to fix or a Handoff to review;
    `instruction` and `review` default to the built-in step's. A step sent back says why in
    place of its instruction; the user's answer follows the instruction."""
    told = INSTRUCTIONS.get(step, "") if instruction is None else instruction
    if feedback.sent_back and not feedback.user:
        head = f"Loop {ticket.loop}, step {step}: {feedback.sent_back}"
    else:
        head = f"Loop {ticket.loop}, step {step}: {told}"
        if feedback.sent_back:
            head = f"{head}\n{feedback.sent_back}"
    if review if review is not None else kind(step) == "review":
        blocks = [("Handoff", sections.get("Handoff", "")), ("Diff stat", diff_stat)]
        blocks += _check_blocks(sections, feedback)
    else:
        blocks = [("Findings", sections.get("Findings", "")), *_check_blocks(sections, feedback)]
    return _join(head, blocks, None)


def _check_blocks(sections: Mapping[str, str], feedback: Feedback) -> list[tuple[str, str]]:
    """`## Check output` for editing steps, then `## Checks`; empty ones drop out in `_join`."""
    output = sections.get("Check output", "") if feedback.editing else ""
    return [("Check output", output), ("Checks", feedback.checks)]


def plan_review_prompt(
    plan: Plan, sections: Mapping[str, str], decisions: str, *, round: int, resumed: bool
) -> str:
    """A plan-review round: the whole plan inline; a new session also gets the decision log,
    a resumed one the Review log (SP3 spec decision 29)."""
    of = f"round {round} of {plan.review.max}"
    if resumed:
        head = f"Round {round} of {plan.review.max}: the planner revised the plan. {PLAN_REVIEW}"
        blocks = [(name, sections.get(name, "")) for name in PLAN_SECTIONS]
    else:
        head = f'You are the plan-reviewer for plan {plan.id} "{plan.title}", {of}.\n{PLAN_REVIEW}'
        blocks = [(name, sections.get(name, "")) for name in PLAN_SECTIONS if name != "Review log"]
        blocks.append(("Decisions log", decisions))
    return _join(head, blocks, REPLY)


def review_log_lines(round: int, output: ReviewOutput) -> list[str]:
    """A round's Review log lines: a pass line, then one line per finding."""
    lines = (
        [f"- round {round} · pass · {_flat(output.summary)}"] if output.verdict == "pass" else []
    )
    lines += [
        f"- round {round} · {f.severity} · {f.file or '-'}:{f.line} · {_flat(f.issue)} · "
        f"{_flat(f.fix)}"
        for f in output.findings
    ]
    return [redact(line) for line in lines]


def compact_prompt(text: str, *, cap: int) -> str:
    """The compactor's prompt: MEMORY.md inline and the rules its result must meet."""
    target = cap * 3 // 4
    return (
        "You compact MEMORY.md, the user's global memory for coding agents: "
        f"{len(text.splitlines())} lines, cap {cap}.\n"
        f"Rewrite it in at most {target} lines: merge duplicates, drop stale or superseded "
        "facts, and keep one fact per line of about 20 words.\n"
        "Keep the title, the intro paragraph and every '## ' heading. Keep every entry "
        "marked (pin) exactly as it is.\n"
        "Everything you need is below: use no tools, read and write no files, and return "
        "the whole new file as text.\n\n"
        f"MEMORY.md:\n```markdown\n{text.rstrip(chr(10))}\n```\n\n{REPLY}"
    )


NETWORK_PROMPT = (
    "Your last turn was cut off by a network error. Your edits are kept; finish the step and reply."
)


RETRY_NOTE = (
    "The worktree already holds changes from a failed attempt; review them and finish the step."
)


def repair_prompt(problem: str) -> str:
    return (
        f"Your last reply failed: {problem}\n"
        "Fix it and reply again with JSON that matches the schema."
    )


def handoff_text(handoff: str) -> str:
    """The Handoff kengash keeps: redacted, at most 15 lines."""
    return "\n".join(redact(handoff).strip("\n").splitlines()[:HANDOFF_LINES])


def findings_text(findings: Sequence[Finding]) -> str:
    return "\n".join(
        redact(f"- {f.severity} · {f.file or '-'}:{f.line} · {f.issue} · {f.fix}") for f in findings
    )


def log_line(
    at: datetime, step: str, role: str, provider: str, model: str | None, verdict: str, tokens: int
) -> str:
    return (
        f"- {at:%Y-%m-%d %H:%M} · {step} · {role} · {provider}/{model or 'default'} · "
        f"{verdict} · {tokens}"
    )


def role_skill(paths: StorePaths, slug: str, skill: str) -> str | None:
    """The role skill's body: project `roles/`, then `defaults/roles/`, then the package."""
    return skills.role_text(paths, slug, skill)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _join(head: str, blocks: Sequence[tuple[str, str]], tail: str | None) -> str:
    parts = [head]
    parts += [f"## {name}\n{text.strip(chr(10))}" for name, text in blocks if text.strip()]
    if tail:
        parts.append(tail)
    return "\n\n".join(parts)
