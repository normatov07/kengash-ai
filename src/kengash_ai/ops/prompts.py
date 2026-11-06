"""What a step's CLI reads and what kengash writes back (SP3 spec §8.2, decision 25)."""

from collections.abc import Mapping, Sequence
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
        ("Diff stat", diff_stat),
    ]
    told = INSTRUCTIONS.get(step, "") if instruction is None else instruction
    return _join(f"{head}\n{told}", blocks, REPLY)


def resumed_prompt(
    ticket: Ticket,
    sections: Mapping[str, str],
    *,
    step: str,
    diff_stat: str,
    instruction: str | None = None,
    review: bool | None = None,
) -> str:
    """A resumed session's prompt: the step, plus Findings to fix or a Handoff to review;
    `instruction` and `review` default to the built-in step's."""
    told = INSTRUCTIONS.get(step, "") if instruction is None else instruction
    head = f"Loop {ticket.loop}, step {step}: {told}"
    if review if review is not None else kind(step) == "review":
        blocks = [("Handoff", sections.get("Handoff", "")), ("Diff stat", diff_stat)]
    else:
        blocks = [("Findings", sections.get("Findings", ""))]
    return _join(head, blocks, None)


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
