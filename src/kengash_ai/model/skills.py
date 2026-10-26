"""Skill frontmatter (Agent Skills format; SP4 spec decisions 3, 9)."""

from pydantic import BaseModel, ConfigDict, Field

NAME_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
NAME_MAX = 64
DESCRIPTION_MAX = 500


class SkillMeta(BaseModel):
    """A SKILL.md frontmatter; keys this model does not name are kept, not refused."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: str
    description: str
    disable_model_invocation: bool = Field(False, alias="disable-model-invocation")
    metadata: dict[str, str] = Field(default_factory=dict)
