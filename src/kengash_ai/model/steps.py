"""Step contract between `ops` and the provider adapters (SP3 spec §8)."""

from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, computed_field, model_validator

Profile = Literal["read_only", "edit_worktree"]
OutputKind = Literal["work", "plan", "review", "compact", "harvest"]
ErrorKind = Literal["auth", "rate_limit", "network", "timeout", "empty", "schema", "crash", "stuck"]


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

    def plus(self, other: "Usage") -> "Usage":
        """Both counts added; a cost only when either side has one."""
        unknown = self.cost_usd is None and other.cost_usd is None
        return Usage(
            input=self.input + other.input,
            output=self.output + other.output,
            cache_read=self.cache_read + other.cache_read,
            cache_write=self.cache_write + other.cache_write,
            cost_usd=None if unknown else (self.cost_usd or 0) + (other.cost_usd or 0),
        )

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


class Decision(_Step):
    """A lasting choice a worker proposes; it reaches DECISIONS.md when the ticket merges
    (SP16 spec §3.3)."""

    decision: str
    why: str
    rejected: str = ""


class WorkOutput(_Step):
    summary: str
    handoff: str
    decisions: list[Decision] = Field(default_factory=list)


class Part(_Step):
    """One slice of a ticket too large for one (SP17 spec §3.6); `after` holds the indexes of
    earlier parts it needs."""

    title: str
    scope: str
    acceptance: list[str]
    files: list[str]
    after: list[int] = Field(default_factory=list)


class PlanOutput(WorkOutput):
    """A read step's reply: the plan, the files it will change (SP16 spec §3.12), and the
    parts of a ticket that has to be split (SP17 spec §3.6)."""

    files: list[str] = Field(default_factory=list)
    parts: list[Part] = Field(default_factory=list)


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


class HarvestFact(_Step):
    """One thing the user settled (SP18 spec §3.1); `quote` holds their own words for it,
    `replaces` the number of a listed decision it overrules (0: none)."""

    kind: Literal["decision", "preference", "working_style", "goal", "turned_down", "process"]
    fact: str
    why: str
    rejected: str = ""
    quote: str
    replaces: int = Field(0, ge=0)


class HarvestOutput(_Step):
    facts: list[HarvestFact] = Field(default_factory=list)


type StepOutput = WorkOutput | PlanOutput | ReviewOutput | CompactOutput | HarvestOutput

_MODELS: dict[OutputKind, type[WorkOutput | ReviewOutput | CompactOutput | HarvestOutput]] = {
    "work": WorkOutput,
    "plan": PlanOutput,
    "review": ReviewOutput,
    "compact": CompactOutput,
    "harvest": HarvestOutput,
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

_DECISIONS: dict[str, Any] = {
    "type": "array",
    "items": _strict({"decision": _TEXT, "why": _TEXT, "rejected": _TEXT}),
}

# Strict: every field required, no extra fields, so claude, codex and agy all accept them.
OUTPUT_SCHEMAS: dict[OutputKind, dict[str, Any]] = {
    "work": _strict({"summary": _TEXT, "handoff": _TEXT, "decisions": _DECISIONS}),
    "plan": _strict(
        {
            "summary": _TEXT,
            "handoff": _TEXT,
            "files": {"type": "array", "items": _TEXT},
            "parts": {
                "type": "array",
                "items": _strict(
                    {
                        "title": _TEXT,
                        "scope": _TEXT,
                        "acceptance": {"type": "array", "items": _TEXT},
                        "files": {"type": "array", "items": _TEXT},
                        "after": {"type": "array", "items": {"type": "integer"}},
                    }
                ),
            },
            "decisions": _DECISIONS,
        }
    ),
    "review": _strict(
        {
            "verdict": {"type": "string", "enum": ["pass", "fail"]},
            "summary": _TEXT,
            "findings": {"type": "array", "items": _FINDING},
        }
    ),
    "compact": _strict({"text": _TEXT}),
    "harvest": _strict(
        {
            "facts": {
                "type": "array",
                "items": _strict(
                    {
                        "kind": {
                            "type": "string",
                            "enum": [
                                "decision",
                                "preference",
                                "working_style",
                                "goal",
                                "turned_down",
                                "process",
                            ],
                        },
                        "fact": _TEXT,
                        "why": _TEXT,
                        "rejected": _TEXT,
                        "quote": _TEXT,
                        "replaces": {"type": "integer"},
                    }
                ),
            }
        }
    ),
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
    commands: list[str] = Field(default_factory=list)  # more commands a worker may run (SP19)
    allow_api_key: bool = False
    user_config: bool = False
    bypass: bool = False
    prior_usage: Usage | None = None
    soft_s: int | None = None  # stop the call this far in and steer it; None: never (SP17)
    poll_max: int = 0  # polls of a background command with no edit between them
    full_runs_max: int = 0  # runs of the whole test command in this call

    @model_validator(mode="after")
    def _resume_has_session(self) -> Self:
        if self.resume and not self.session_id:
            raise ValueError("resume needs a session_id")
        return self


class StepResult(_Step):
    """What one CLI call returned; `error` is None on success."""

    session_id: str | None = None
    output: WorkOutput | ReviewOutput | CompactOutput | HarvestOutput | None = None
    text: str = ""
    usage: Usage = Field(default_factory=Usage)
    total_usage: Usage | None = None
    duration_s: float = 0.0
    error: ErrorKind | None = None
    retry_after: datetime | None = None
    detail: str = ""
    warning: str = ""  # an error the CLI reported after a valid output (SP12 spec §3.1)
    check_output: str = ""  # a failing check's digest, for `## Check output` (SP15 spec §3.3)

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
    live_models: bool = False  # `models` is the CLI's own list, not a set of aliases (SP17)

    @property
    def usable(self) -> bool:
        return self.installed and self.signed_in
