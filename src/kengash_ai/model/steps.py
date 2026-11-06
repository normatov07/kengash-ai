"""Step contract between `ops` and the provider adapters (SP3 spec §8)."""

from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, computed_field, model_validator

Profile = Literal["read_only", "edit_worktree"]
OutputKind = Literal["work", "review", "compact"]
ErrorKind = Literal["auth", "rate_limit", "network", "timeout", "empty", "schema", "crash"]


class _Step(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Usage(_Step):
    """Tokens one step used; `input` excludes cache reads, `output` includes thinking."""

    input: NonNegativeInt = 0
    output: NonNegativeInt = 0
    cache_read: NonNegativeInt = 0
    cache_write: NonNegativeInt = 0
    cost_usd: float | None = None

    @property
    def tokens(self) -> int:
        """What a step adds to the ticket's `tokens` (decision 10)."""
        return self.input + self.output

    def minus(self, prior: "Usage | None") -> "Usage":
        """These running totals less an earlier turn's, floored at 0; cost is dropped."""
        prior = prior or Usage()
        return Usage(
            input=max(self.input - prior.input, 0),
            output=max(self.output - prior.output, 0),
            cache_read=max(self.cache_read - prior.cache_read, 0),
            cache_write=max(self.cache_write - prior.cache_write, 0),
        )


class Finding(_Step):
    severity: Literal["high", "medium", "low"]
    file: str
    line: NonNegativeInt
    issue: str
    fix: str


class WorkOutput(_Step):
    summary: str
    handoff: str


class ReviewOutput(_Step):
    verdict: Literal["pass", "fail"]
    summary: str
    findings: list[Finding]

    @model_validator(mode="after")
    def _fail_has_findings(self) -> Self:
        if self.verdict == "fail" and not self.findings:
            raise ValueError("a failing verdict needs findings")
        return self


class CompactOutput(_Step):
    text: str


type StepOutput = WorkOutput | ReviewOutput | CompactOutput

_MODELS: dict[OutputKind, type[WorkOutput | ReviewOutput | CompactOutput]] = {
    "work": WorkOutput,
    "review": ReviewOutput,
    "compact": CompactOutput,
}


def _strict(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_TEXT: dict[str, Any] = {"type": "string"}
_FINDING = _strict(
    {
        "severity": {"type": "string", "enum": ["high", "medium", "low"]},
        "file": _TEXT,
        "line": {"type": "integer"},
        "issue": _TEXT,
        "fix": _TEXT,
    }
)

# Strict: every field required, no extra fields, so claude, codex and agy all accept them.
OUTPUT_SCHEMAS: dict[OutputKind, dict[str, Any]] = {
    "work": _strict({"summary": _TEXT, "handoff": _TEXT}),
    "review": _strict(
        {
            "verdict": {"type": "string", "enum": ["pass", "fail"]},
            "summary": _TEXT,
            "findings": {"type": "array", "items": _FINDING},
        }
    ),
    "compact": _strict({"text": _TEXT}),
}


def parse_output(kind: OutputKind, data: object) -> StepOutput:
    """Validate a CLI's structured output; raises ValueError when it misses the schema."""
    return _MODELS[kind].model_validate(data)


class StepRequest(_Step):
    """One CLI call: what to ask, where, and under which permissions."""

    role: str
    cwd: Path
    prompt: str
    output: OutputKind
    profile: Profile
    timeout_s: int = Field(ge=1)
    log: Path
    model: str | None = None
    session_id: str | None = None
    resume: bool = False
    skill: str | None = None
    test_cmd: str = ""
    lint_cmd: str = ""
    allow_api_key: bool = False
    user_config: bool = False
    bypass: bool = False
    prior_usage: Usage | None = None

    @model_validator(mode="after")
    def _resume_has_session(self) -> Self:
        if self.resume and not self.session_id:
            raise ValueError("resume needs a session_id")
        return self


class StepResult(_Step):
    """What one CLI call returned; `error` is None on success."""

    session_id: str | None = None
    output: WorkOutput | ReviewOutput | CompactOutput | None = None
    text: str = ""
    usage: Usage = Field(default_factory=Usage)
    total_usage: Usage | None = None
    duration_s: float = 0.0
    error: ErrorKind | None = None
    retry_after: datetime | None = None
    detail: str = ""
    warning: str = ""  # an error the CLI reported after a valid output (SP12 spec §3.1)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ok(self) -> bool:
        return self.error is None


class ProviderStatus(_Step):
    """A provider CLI's install and sign-in state."""

    name: str
    installed: bool
    version: str | None = None
    signed_in: bool = False
    auth_method: str | None = None
    hint: str = ""
    models: list[str] = []  # what `--model` takes, when the CLI says (SP10 §5.2)

    @property
    def usable(self) -> bool:
        return self.installed and self.signed_in
