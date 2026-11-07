"""The project's checks inside an editing step (SP15 spec §3.1): whether they run after a
step, the shell request that runs them, and what a run reports."""

from pathlib import Path

from kengash_ai import workflow
from kengash_ai.model import Gate, ReviewOutput, Settings, StepRequest, StepResult, Ticket
from kengash_ai.ops import calls


def wanted(resolved: Settings, ticket: Ticket, step: str) -> bool:
    """Checks run after `step` when fix turns are on, a command is set, and a check step that
    is on follows it in the ticket's workflow (a workflow without one chose not to test)."""
    project = resolved.project
    if resolved.checks.turns == 0 or not (project.test_cmd.strip() or project.lint_cmd.strip()):
        return False
    order = workflow.steps_for(resolved, ticket.workflow, hitl=ticket.gate is Gate.hitl)
    if step not in order:
        return False
    return any(resolved.kind_of(later) == "check" for later in order[order.index(step) + 1 :])


def configured(resolved: Settings, ticket: Ticket) -> bool:
    """The project has a test or lint command and the ticket's workflow an enabled `check`
    step: a merge onto a moved base reruns them (SP16 spec §3.9)."""
    project = resolved.project
    if not (project.test_cmd.strip() or project.lint_cmd.strip()):
        return False
    if ticket.workflow not in resolved.workflows:
        return False
    order = workflow.steps_for(resolved, ticket.workflow, hitl=ticket.gate is Gate.hitl)
    return any(resolved.kind_of(step) == "check" for step in order)


def request(resolved: Settings, worktree: Path, log: Path) -> StepRequest:
    """The shell request that runs `test_cmd`, then `lint_cmd`, in the worktree."""
    return StepRequest(
        role="test-runner",
        cwd=worktree,
        prompt="",
        output="review",
        profile="read_only",
        timeout_s=calls.step_timeout(resolved),
        log=log,
        test_cmd=resolved.project.test_cmd,
        lint_cmd=resolved.project.lint_cmd,
    )


def outcome(result: StepResult) -> tuple[str, str]:
    """A check run's verdict (`pass`, `fail`, `timeout` or `error`) and its summary."""
    if isinstance(result.output, ReviewOutput):
        return result.output.verdict, result.output.summary
    if result.error == "timeout":
        return "timeout", f"checks timed out ({result.detail})"
    return "error", result.detail or str(result.error)
