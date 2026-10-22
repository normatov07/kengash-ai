"""registry.yaml: the projects the store knows (system spec §4.1)."""

from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class ProjectEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    path: Path
    base: str = "main"
    added: date


class Registry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projects: dict[str, ProjectEntry] = Field(default_factory=dict)
