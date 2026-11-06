"""`run_tests` steps: `project.test_cmd`, then `project.lint_cmd`, each `sh -c` in the
worktree; both exit 0 to pass (SP12: lint runs too)."""

import os
from pathlib import Path

from kengash_ai.adapters.base import tail, timed_out
from kengash_ai.adapters.env import worker_env
from kengash_ai.adapters.process import run_process
from kengash_ai.model import (
    Finding,
    ProviderStatus,
    ReviewOutput,
    StepRequest,
    StepResult,
    UserError,
)


class Shell:
    name = "shell"

    def detect(self) -> ProviderStatus:
        return ProviderStatus(name=self.name, installed=True, signed_in=True)

    def run(self, req: StepRequest) -> StepResult:
        checks = [
            (name, command, key)
            for name, command, key in (
                ("tests", req.test_cmd, "project.test_cmd"),
                ("lint", req.lint_cmd, "project.lint_cmd"),
            )
            if command.strip()
        ]
        if not checks:
            return StepResult(error="crash", detail="set project.test_cmd")
        env = worker_env(os.environ, self.name, req.role, allow_api_key=False)
        texts: list[str] = []
        duration = 0.0
        for number, (name, command, key) in enumerate(checks):
            log = req.log if number == 0 else req.log.with_name(f"{req.log.stem}-{name}.out")
            proc = run_process(
                ["sh", "-c", command], cwd=req.cwd, env=env, timeout_s=req.timeout_s, log=log
            )
            duration += proc.duration_s
            texts.append(proc.stdout)
            if proc.timed_out:
                return timed_out(req, proc)
            if proc.exit_code != 0:
                joiner = "\n" if proc.stdout and not proc.stdout.endswith("\n") else ""
                issue = tail(proc.stdout + joiner + proc.stderr) or f"exit {proc.exit_code}"
                finding = Finding(
                    severity="high", file="", line=0, issue=issue, fix=f"make {key} pass"
                )
                summary = f"{name} failed (exit {proc.exit_code})"
                output = ReviewOutput(verdict="fail", summary=summary, findings=[finding])
                return StepResult(output=output, text="".join(texts), duration_s=duration)
        summary = " and ".join(name for name, _, _ in checks) + " passed"
        output = ReviewOutput(verdict="pass", summary=summary, findings=[])
        return StepResult(output=output, text="".join(texts), duration_s=duration)

    def attach_command(self, session_id: str) -> list[str]:
        raise UserError("shell steps have no session")

    def recover_session(self, log: Path) -> str | None:
        return None
