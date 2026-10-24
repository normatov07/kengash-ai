"""SETTINGS.md schema (system spec §4.6). Unknown keys are rejected."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, field_validator, model_validator

STEP_ROLES: dict[str, str | None] = {
    "plan": "planner",
    "review_plan": "plan-reviewer",
    "implement": "implementer",
    "review_code": "code-reviewer",
    "security": "security-reviewer",
    "run_tests": "test-runner",
    "docs": "doc-writer",
    "approve": None,
}
PROVIDERS = ("claude", "codex", "antigravity", "gemini")
SHELL = "shell"


def split_cli(cli: str) -> tuple[str, str | None]:
    """`claude/opus` → ("claude", "opus"); `codex` → ("codex", None): the CLI's default."""
    provider, _, model = cli.partition("/")
    return provider, model or None


def _known(cli: str, *, shell: bool = False) -> str:
    provider, _ = split_cli(cli)
    known = (*PROVIDERS, SHELL) if shell else PROVIDERS
    if provider not in known:
        raise ValueError(f"unknown provider {provider!r}; known: {', '.join(known)}")
    return cli


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectCommands(_Section):
    test_cmd: str = ""
    lint_cmd: str = ""


class LoopMax(_Section):
    simple: int = Field(3, ge=1)
    standard: int = Field(4, ge=1)
    critical: int = Field(6, ge=1)


class Grill(_Section):
    round_size: int = Field(3, ge=1, le=4)


class PlanReview(_Section):
    review_max: int = Field(2, ge=0)
    reviewer: str = "different-provider"  # or provider[/model]

    @field_validator("reviewer")
    @classmethod
    def _reviewer(cls, value: str) -> str:
        return value if value == "different-provider" else _known(value)


def _default_slots() -> dict[str, NonNegativeInt]:
    return {"claude": 3, "codex": 3, "antigravity": 2, "gemini": 0}


class Sessions(_Section):
    reuse: bool = True
    max: int = Field(8, ge=1)
    per_provider: dict[str, NonNegativeInt] = Field(default_factory=_default_slots)


class Tokens(_Section):
    per_ticket_max: int = Field(250_000, ge=1)


class SkillCaps(_Section):
    max_lines: int = Field(80, ge=1)
    max_words: int = Field(400, ge=1)


class MemoryCaps(_Section):
    compact_at_lines: int = Field(200, ge=10)
    compactor: str = "claude/haiku"

    @field_validator("compactor")
    @classmethod
    def _model_provider(cls, value: str) -> str:
        return _known(value)


class ReviewPolicy(_Section):
    diff_only: bool = True


class Agent(_Section):
    on: bool = True
    cli: str
    skill: str
    blocking: bool = False
    fallback: list[str] = Field(default_factory=list)
    bypass_permissions: bool = False

    @field_validator("cli")
    @classmethod
    def _cli_provider(cls, value: str) -> str:
        return _known(value, shell=True)

    @field_validator("fallback")
    @classmethod
    def _fallback_providers(cls, value: list[str]) -> list[str]:
        for cli in value:
            _known(cli)
        return value


class ProviderOptions(_Section):
    allow_api_key: bool = False
    user_config: bool = False


class Workflow(_Section):
    steps: list[str] = Field(min_length=1)
    on_fail: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _known_steps(self) -> Self:
        unknown = [step for step in self.steps if step not in STEP_ROLES]
        if unknown:
            raise ValueError(f"unknown steps {unknown}; known: {', '.join(STEP_ROLES)}")
        stray = [
            f"{source}->{target}"
            for source, target in self.on_fail.items()
            if source not in self.steps or target not in self.steps
        ]
        if stray:
            raise ValueError(f"on_fail edges must join steps of this workflow: {', '.join(stray)}")
        return self


class StatusNames(_Section):
    names: dict[str, str] = Field(default_factory=dict)


class Merge(_Section):
    mode: Literal["ask", "auto", "branch"] = "ask"


class Settings(_Section):
    version: Literal[1] = 1
    project: ProjectCommands = Field(default_factory=ProjectCommands)
    loop_max: LoopMax = Field(default_factory=LoopMax)
    loop_grant: int = Field(2, ge=1)
    loop_ask_at_cap: bool = True
    loop_count_rejected_review: bool = True
    stall_repeat: int = Field(2, ge=1)
    grill: Grill = Field(default_factory=Grill)
    plan: PlanReview = Field(default_factory=PlanReview)
    sessions: Sessions = Field(default_factory=Sessions)
    tokens: Tokens = Field(default_factory=Tokens)
    step_timeout_min: int = Field(30, ge=1)
    fallback_on_rate_limit: bool = True
    skill: SkillCaps = Field(default_factory=SkillCaps)
    memory: MemoryCaps = Field(default_factory=MemoryCaps)
    review: ReviewPolicy = Field(default_factory=ReviewPolicy)
    providers: dict[str, ProviderOptions] = Field(default_factory=dict)
    agents: dict[str, Agent] = Field(default_factory=dict)
    workflows: dict[str, Workflow] = Field(default_factory=dict)
    status: StatusNames = Field(default_factory=StatusNames)
    merge: Merge = Field(default_factory=Merge)

    @model_validator(mode="after")
    def _steps_have_agents(self) -> Self:
        missing = sorted(
            {
                f"{step}: {role}"
                for workflow in self.workflows.values()
                for step in workflow.steps
                if (role := STEP_ROLES[step]) is not None and role not in self.agents
            }
        )
        if missing:
            raise ValueError(f"workflow steps need agents: {', '.join(missing)}")
        return self

    @field_validator("providers")
    @classmethod
    def _provider_names(cls, value: dict[str, ProviderOptions]) -> dict[str, ProviderOptions]:
        unknown = sorted(set(value) - set(PROVIDERS))
        if unknown:
            raise ValueError(f"unknown providers {unknown}; known: {', '.join(PROVIDERS)}")
        return value

    def provider(self, name: str) -> ProviderOptions:
        """A provider's worker options; providers left out of SETTINGS get the defaults."""
        return self.providers.get(name, ProviderOptions())
