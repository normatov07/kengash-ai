"""`run_tests` steps: `sh -c <project.test_cmd>` in the worktree; exit 0 passes."""

import os
from pathlib import Path

from super_harness.adapters.base import tail, timed_out
from super_harness.adapters.env import worker_env
from super_harness.adapters.process import run_process
from super_harness.model import (
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
        if not req.test_cmd.strip():
            return StepResult(error="crash", detail="set project.test_cmd")
        env = worker_env(os.environ, self.name, req.role, allow_api_key=False)
        proc = run_process(
            ["sh", "-c", req.test_cmd], cwd=req.cwd, env=env, timeout_s=req.timeout_s, log=req.log
        )
        if proc.timed_out:
            return timed_out(req, proc)
        if proc.exit_code == 0:
            output = ReviewOutput(verdict="pass", summary="tests passed", findings=[])
        else:
            joiner = "\n" if proc.stdout and not proc.stdout.endswith("\n") else ""
            issue = tail(proc.stdout + joiner + proc.stderr) or f"exit {proc.exit_code}"
            finding = Finding(
                severity="high", file="", line=0, issue=issue, fix="make project.test_cmd pass"
            )
            summary = f"tests failed (exit {proc.exit_code})"
            output = ReviewOutput(verdict="fail", summary=summary, findings=[finding])
        return StepResult(output=output, text=proc.stdout, duration_s=proc.duration_s)

    def attach_command(self, session_id: str) -> list[str]:
        raise UserError("shell steps have no session")

    def recover_session(self, log: Path) -> str | None:
        return None
