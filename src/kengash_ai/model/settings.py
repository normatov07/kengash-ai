"""SETTINGS.md schema (system spec §4.6, SP6 custom steps, SP10 routing and fixed built-in
skills). Unknown keys are rejected."""

import re
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
# What a step does: read (read-only notes, like plan), edit (edits the worktree, like
# implement), review (verdict on the diff, like review_code); check is run_tests' shell verdict
type StepKind = Literal["read", "edit", "review"]
type Kind = Literal["read", "edit", "review", "check"]
BUILTIN_KINDS: dict[str, Kind | None] = {
    "plan": "read",
    "review_plan": "review",
    "implement": "edit",
    "review_code": "review",
    "security": "review",
    "run_tests": "check",
    "docs": "edit",
    "approve": None,
}
# what each built-in role runs; a user changes it only by copying the agent (SP10 §4.1)
BUILTIN_SKILLS = {
    "planner": "plan",
    "plan-reviewer": "review-plan",
    "implementer": "implement",
    "code-reviewer": "review-code",
    "security-reviewer": "review-security",
    "test-runner": "run-tests",
    "doc-writer": "sync-docs",
}
IMPORTANCES = ("simple", "standard", "critical")
STEP_NAME = re.compile(r"[a-z][a-z0-9_]{1,30}")
WORKFLOW_NAME = re.compile(r"[a-z][a-z0-9_-]{0,30}")
MODEL_MAX = 100
# a role names its skill folder too, so it follows the skill-name rule
ROLE_NAME = re.compile(r"(?=.{2,31}$)[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
PROVIDERS = ("claude", "codex", "antigravity")
# A provider kengash no longer drives, its replacement and why (SP7 spec decision 15)
REPLACED = {
    "gemini": (
        "antigravity",
        "Google moved Gemini CLI's Pro, Ultra and free plans to Antigravity CLI on 2026-06-18",
    ),
}


def replaced(provider: str) -> str:
    """The message for a provider that was replaced."""
    successor, why = REPLACED[provider]
    return f"{provider} is replaced by {successor}: {why}; use {successor}"


SHELL = "shell"


def split_cli(cli: str) -> tuple[str, str | None]:
    """`claude/opus` → ("claude", "opus"); `codex` → ("codex", None): the CLI's default."""
    provider, _, model = cli.partition("/")
    return provider, model or None


def _known(cli: str, *, allow_shell: bool = False) -> str:
    provider, slash, model = cli.partition("/")
    if slash and (not model or len(model) > MODEL_MAX or any(c.isspace() for c in model)):
        raise ValueError(f"model must be one word: {cli}")
    if provider in REPLACED:
        raise ValueError(replaced(provider))
    known = (*PROVIDERS, SHELL) if allow_shell else PROVIDERS
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
    return {"claude": 3, "codex": 3, "antigravity": 2}


class Sessions(_Section):
    reuse: bool = True
    max: int = Field(8, ge=1)
    per_provider: dict[str, NonNegativeInt] = Field(default_factory=_default_slots)

    @field_validator("per_provider")
    @classmethod
    def _drop_replaced(cls, value: dict[str, int]) -> dict[str, int]:
        # every project copied `gemini: 0` from the old defaults; it is harmless, so it goes
        return {name: slots for name, slots in value.items() if name not in REPLACED}


class Tokens(_Section):
    per_ticket_max: int = Field(1_000_000, ge=1)  # SP12: was 250,000


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


class Logs(_Section):
    keep_days: int = Field(30, ge=0)  # 0 keeps every log


class Watch(_Section):
    """Viewer tabs and notifications (SP13 spec §3.7)."""

    tabs: Literal["auto", "off"] = "auto"  # a tab per worker and a dashboard per loop
    terminal: str = ""  # a command with {title} and {command}; empty: detect the terminal
    notify: bool = True  # a desktop notification when a ticket needs the user


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
        return _known(value, allow_shell=True)

    @field_validator("fallback")
    @classmethod
    def _fallback_providers(cls, value: list[str]) -> list[str]:
        for cli in value:
            _known(cli)
        return value


class ProviderOptions(_Section):
    allow_api_key: bool = False
    user_config: bool = False


class CustomStep(_Section):
    """A user's step: the role that runs it, its kind, and its one-line instruction."""

    role: str
    kind: StepKind
    does: str = Field(min_length=1)

    @field_validator("does")
    @classmethod
    def _one_line(cls, value: str) -> str:
        if "\n" in value or "\r" in value or len(value) > 200:
            raise ValueError("does must be one line of at most 200 characters")
        return value


class Workflow(_Section):
    steps: list[str] = Field(min_length=1)
    on_fail: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _edges_inside(self) -> Self:
        stray = [
            f"{source}->{target}"
            for source, target in self.on_fail.items()
            if source not in self.steps or target not in self.steps
        ]
        if stray:
            raise ValueError(f"on_fail edges must join steps of this workflow: {', '.join(stray)}")
        forward = [
            f"{source}->{target}"
            for source, target in self.on_fail.items()
            if self.steps.index(target) >= self.steps.index(source)
        ]
        if forward:
            message = "on_fail edges must send back to an earlier step"
            raise ValueError(f"{message}: {', '.join(forward)}")
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
    loop_start: Literal["ask", "auto"] = "ask"  # auto: the loop starts once tickets are added
    grill: Grill = Field(default_factory=Grill)
    plan: PlanReview = Field(default_factory=PlanReview)
    sessions: Sessions = Field(default_factory=Sessions)
    tokens: Tokens = Field(default_factory=Tokens)
    step_timeout_min: int = Field(30, ge=1)
    fallback_on_error: bool = True  # rate limits and network errors use the fallback (SP12)
    skill: SkillCaps = Field(default_factory=SkillCaps)
    memory: MemoryCaps = Field(default_factory=MemoryCaps)
    review: ReviewPolicy = Field(default_factory=ReviewPolicy)
    logs: Logs = Field(default_factory=Logs)
    watch: Watch = Field(default_factory=Watch)
    providers: dict[str, ProviderOptions] = Field(default_factory=dict)
    agents: dict[str, Agent] = Field(default_factory=dict)
    steps: dict[str, CustomStep] = Field(default_factory=dict)
    workflows: dict[str, Workflow] = Field(default_factory=dict)
    routing: dict[str, str] = Field(default_factory=dict)  # importance → workflow
    status: StatusNames = Field(default_factory=StatusNames)
    merge: Merge = Field(default_factory=Merge)

    @model_validator(mode="after")
    def _custom_steps(self) -> Self:
        for name, step in self.steps.items():
            if name in STEP_ROLES:
                raise ValueError(f"steps.{name}: {name} is a built-in step")
            if not STEP_NAME.fullmatch(name):
                raise ValueError(f"steps.{name}: step name must match {STEP_NAME.pattern}")
            if not ROLE_NAME.fullmatch(step.role):
                raise ValueError(
                    f"steps.{name}: role name must be lowercase words joined by single "
                    "hyphens, 2 to 31 characters"
                )
            if step.role not in self.agents:
                raise ValueError(f"steps.{name}: no agent {step.role!r} in agents")
            if split_cli(self.agents[step.role].cli)[0] == SHELL:
                # shell only runs project.test_cmd; it never reads a step's instruction
                raise ValueError(f"steps.{name}: {step.role} needs a model CLI, not shell")
        return self

    @model_validator(mode="after")
    def _builtin_skills(self) -> Self:
        for role, skill in BUILTIN_SKILLS.items():
            agent = self.agents.get(role)
            if agent is not None and agent.skill != skill:
                raise ValueError(
                    f"agents.{role}.skill is fixed at {skill}; set it back, or copy the agent "
                    f"(kengash agent copy {role} <new>) to change what it does"
                )
        return self

    @model_validator(mode="after")
    def _workflows_and_routing(self) -> Self:
        for name, flow in self.workflows.items():
            if not WORKFLOW_NAME.fullmatch(name):
                raise ValueError(f"workflow name must match {WORKFLOW_NAME.pattern}")
            twice = sorted({step for step in flow.steps if flow.steps.count(step) > 1})
            if twice:
                raise ValueError(f"workflows.{name}: step {twice[0]} appears twice")
        for importance, target in self.routing.items():
            if importance not in IMPORTANCES:
                raise ValueError(f"routing: unknown importance {importance}")
            if target not in self.workflows:
                raise ValueError(f"routing.{importance}: no workflow {target}")
        return self

    def workflow_for(self, importance: str) -> str:
        """The workflow a new ticket of `importance` runs: its routing entry, else the
        workflow named like the importance."""
        return self.routing.get(importance, importance)

    @model_validator(mode="after")
    def _steps_have_agents(self) -> Self:
        known = self.step_names()
        for name, flow in self.workflows.items():
            unknown = [step for step in flow.steps if step not in known]
            if unknown:
                raise ValueError(
                    f"workflows.{name}: unknown steps {unknown}; known: {', '.join(known)}"
                )
            for source in flow.on_fail:
                if source in self.steps and self.steps[source].kind != "review":
                    raise ValueError(
                        f"workflows.{name}: on_fail from {source}: only review steps send back"
                    )
        missing = sorted(
            {
                f"{step}: {role}"
                for workflow in self.workflows.values()
                for step in workflow.steps
                if (role := self.role_of(step)) is not None and role not in self.agents
            }
        )
        if missing:
            raise ValueError(f"workflow steps need agents: {', '.join(missing)}")
        return self

    def role_of(self, step: str) -> str | None:
        """The role that runs `step`: built-in or custom; None for approve or an unknown step."""
        custom = self.steps.get(step)
        return custom.role if custom is not None else STEP_ROLES.get(step)

    def kind_of(self, step: str) -> Kind | None:
        """What `step` does (see StepKind); None for approve or an unknown step."""
        custom = self.steps.get(step)
        return custom.kind if custom is not None else BUILTIN_KINDS.get(step)

    def step_names(self) -> list[str]:
        """Every step a workflow may use: the built-ins, then the custom steps."""
        return [*STEP_ROLES, *self.steps]

    @field_validator("providers")
    @classmethod
    def _provider_names(cls, value: dict[str, ProviderOptions]) -> dict[str, ProviderOptions]:
        for name in value:
            if name in REPLACED:
                raise ValueError(replaced(name))
        unknown = sorted(set(value) - set(PROVIDERS))
        if unknown:
            raise ValueError(f"unknown providers {unknown}; known: {', '.join(PROVIDERS)}")
        return value

    def provider(self, name: str) -> ProviderOptions:
        """A provider's worker options; providers left out of SETTINGS get the defaults."""
        return self.providers.get(name, ProviderOptions())
