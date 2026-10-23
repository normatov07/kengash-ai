"""Skill eval scenarios, `evals/<skill>/<scenario>.yaml` (SP4 spec decision 11)."""

from pydantic import BaseModel, ConfigDict, Field


class _Eval(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetupStep(_Eval):
    """One `harness` command run before the conductor starts."""

    args: list[str]
    stdin: str = ""
    save: str | None = None  # keep the first 8-hex word it prints as {save}


class RecordsExpect(_Eval):
    """What every plan (or ticket) in the store must look like, and how many there are."""

    count: int | None = None
    min: int | None = None
    fields: dict[str, str] = Field(default_factory=dict)  # dotted keys, e.g. review.round


class Expect(_Eval):
    journal: list[str] = Field(default_factory=list)  # event types that must appear
    absent: list[str] = Field(default_factory=list)  # event types that must not
    plans: RecordsExpect | None = None
    tickets: RecordsExpect | None = None
    memory: list[str] = Field(default_factory=list)  # text MEMORY.md must hold
    decisions: list[str] = Field(default_factory=list)
    reply: list[str] = Field(default_factory=list)  # text the last reply must hold


class EvalScenario(_Eval):
    skill: str
    description: str = ""
    notes: str = ""  # e.g. how the scenario failed without the skill
    files: dict[str, str] = Field(default_factory=dict)
    settings: str = ""
    setup: list[SetupStep] = Field(default_factory=list)
    turns: list[str] = Field(min_length=1)
    expect: Expect
    timeout_s: int = Field(900, ge=1)
